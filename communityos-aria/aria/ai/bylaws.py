"""aria.ai.bylaws — Citation-grounded bylaw lookup.

Indexes a building's bylaws (per-org), retrieves the top matching sections
for a question, and returns chunks WITH structured citation metadata
(section number, title, page) so the LLM can cite sources verbatim.

The killer Canadian-condo feature: residents ask "Can I install hardwood
floors?", "Are pets allowed?", "What time do quiet hours start?", and
ARIA answers with the exact section reference instead of guessing.

Storage: in-process per-org index with sentence-transformers embeddings
when available (graceful BM25-ish fallback otherwise). Persists to disk
under ``aria/resources/bylaws_index/<org_id>.json`` so a service restart
is fast.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

logger = logging.getLogger("aria.ai.bylaws")

CHUNK_DIR = Path("aria/resources/bylaws_index")
TOP_K_DEFAULT = 4
SCORE_FLOOR_EMBED = 0.25
SCORE_FLOOR_LEXICAL = 0.0    # lexical fallback uses raw co-occurrence; keep
                             # the threshold off and rely on top-K cutoff
                             # plus rare-token boosting below.


@dataclass
class BylawChunk:
    """One indexed unit. Chunk_id is a stable hash so re-ingest is idempotent."""
    org_id: str
    section_number: str        # e.g. "3.2"
    section_title: str         # e.g. "Hardwood Flooring"
    text: str
    page: int | None = None
    chunk_id: str = ""
    embedding: list[float] | None = None

    def citation(self) -> str:
        """Human-friendly citation token, e.g. '§3.2 Hardwood Flooring'."""
        return f"§{self.section_number} {self.section_title}".strip()


# ── Helpers ────────────────────────────────────────────────────────────


_SECTION_RE = re.compile(
    r"^\s*(?:Section\s+|§\s*)?(\d+(?:\.\d+)*)\s+(.+?)\s*$",
    flags=re.IGNORECASE,
)


def _parse_sections(raw: str) -> list[tuple[str, str, str]]:
    """Parse a structured bylaw document into (section_number, title, body) tuples.

    Expected document format:
        Section 1.0  General
        Body paragraph 1.
        Body paragraph 2.

        Section 2.0  Pets
        ...

    A blank line separates sections. The first line of each section is
    expected to be a heading like "Section X.Y Title" or "X.Y Title".
    Anything that doesn't fit this shape is attached to the previous section.
    """
    sections: list[tuple[str, str, str]] = []
    current_num: str | None = None
    current_title: str = ""
    body_lines: list[str] = []

    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        m = _SECTION_RE.match(line) if line.strip() else None
        # Heuristic: only treat as a heading when section number has a dot
        # OR the line starts with the literal word "Section"/"§" — avoids
        # matching every numbered list item inside body text.
        looks_like_heading = bool(
            m and (
                "." in m.group(1)
                or line.strip().lower().startswith(("section ", "§"))
            )
        )

        if looks_like_heading:
            if current_num is not None:
                sections.append(
                    (current_num, current_title, "\n".join(body_lines).strip())
                )
            current_num = m.group(1)
            current_title = m.group(2).strip()
            body_lines = []
        else:
            body_lines.append(line)

    if current_num is not None:
        sections.append((current_num, current_title, "\n".join(body_lines).strip()))
    return sections


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / denom if denom else 0.0


# ── Index ──────────────────────────────────────────────────────────────


class BylawIndex:
    """Per-org bylaw retrieval index. One instance shared process-wide."""

    def __init__(self):
        self._by_org: dict[str, list[BylawChunk]] = {}
        self._model = None
        self._embeddings_available = False
        self._lock = Lock()
        self._load_model()

    def _load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._embeddings_available = True
            logger.info("Bylaw index: sentence-transformers loaded")
        except Exception as e:
            logger.info("Bylaw index: using lexical fallback (%s)", e)

    def ingest_text(self, org_id: str, raw_text: str) -> int:
        """Parse + index a bylaw document. Replaces any prior index for this org."""
        sections = _parse_sections(raw_text)
        chunks: list[BylawChunk] = []
        for num, title, body in sections:
            if not body:
                continue
            chunk_id = hashlib.md5(f"{org_id}:{num}:{title}".encode()).hexdigest()[:12]
            chunks.append(BylawChunk(
                org_id=org_id,
                section_number=num,
                section_title=title,
                text=body,
                chunk_id=chunk_id,
            ))

        if self._embeddings_available and chunks:
            try:
                texts = [f"{c.section_title}\n{c.text}" for c in chunks]
                embs = self._model.encode(texts, normalize_embeddings=True)
                for c, e in zip(chunks, embs):
                    c.embedding = [float(x) for x in e]
            except Exception as ex:
                logger.warning("Bylaw embedding failed: %s", ex)

        with self._lock:
            self._by_org[org_id] = chunks
        logger.info("Bylaw index: ingested %d sections for %s", len(chunks), org_id)
        return len(chunks)

    def retrieve(self, org_id: str, query: str, top_k: int = TOP_K_DEFAULT) -> list[BylawChunk]:
        """Top-K bylaw chunks ranked by relevance to the question."""
        if not query:
            return []
        chunks = self._by_org.get(org_id) or []
        if not chunks:
            return []

        if self._embeddings_available:
            try:
                q_emb = [float(x) for x in self._model.encode([query], normalize_embeddings=True)[0]]
                scored = [
                    (c, _cosine(q_emb, c.embedding))
                    for c in chunks if c.embedding
                ]
                scored.sort(key=lambda x: x[1], reverse=True)
                return [c for c, score in scored[:top_k] if score >= SCORE_FLOOR_EMBED]
            except Exception as e:
                logger.warning("Bylaw embed retrieval failed: %s", e)

        # Lexical fallback — TF-style scoring with IDF-ish boost for tokens
        # that appear in only one or two sections. Section title tokens
        # weigh 2x because titles are highly indicative.
        STOPWORDS = {
            "the", "a", "an", "is", "are", "in", "on", "of", "to", "and",
            "or", "but", "for", "at", "by", "with", "from", "as", "i",
            "my", "me", "we", "you", "this", "that", "what", "can", "do",
            "does", "have", "has", "be", "it", "its", "any", "some",
        }
        q_tokens = [t for t in _tokenize(query) if t not in STOPWORDS]
        if not q_tokens:
            return []

        # Token → number of chunks containing it (for IDF)
        df: Counter = Counter()
        for c in chunks:
            for t in set(_tokenize(f"{c.section_title} {c.text}")):
                df[t] += 1

        scored: list[tuple[BylawChunk, float]] = []
        for c in chunks:
            title_tokens = set(_tokenize(c.section_title))
            body_tokens = Counter(_tokenize(c.text))
            score = 0.0
            for qt in q_tokens:
                if qt in body_tokens or qt in title_tokens:
                    # Rare tokens count more (idf-ish)
                    idf = math.log(1 + (len(chunks) / max(1, df.get(qt, 1))))
                    weight = 2.0 if qt in title_tokens else 1.0
                    score += weight * idf
            if score > 0:
                scored.append((c, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_k]]

    def has_org(self, org_id: str) -> bool:
        return bool(self._by_org.get(org_id))

    def size(self, org_id: str) -> int:
        return len(self._by_org.get(org_id) or [])

    # Persistence
    def save(self, org_id: str, dir_path: Path = CHUNK_DIR) -> None:
        chunks = self._by_org.get(org_id)
        if not chunks:
            return
        dir_path.mkdir(parents=True, exist_ok=True)
        out = [{
            "section_number": c.section_number,
            "section_title": c.section_title,
            "text": c.text,
            "page": c.page,
            "chunk_id": c.chunk_id,
            "embedding": c.embedding,
        } for c in chunks]
        (dir_path / f"{org_id}.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8"
        )

    def load(self, org_id: str, dir_path: Path = CHUNK_DIR) -> bool:
        fp = dir_path / f"{org_id}.json"
        if not fp.exists():
            return False
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            chunks = [
                BylawChunk(
                    org_id=org_id,
                    section_number=d["section_number"],
                    section_title=d["section_title"],
                    text=d["text"],
                    page=d.get("page"),
                    chunk_id=d.get("chunk_id", ""),
                    embedding=d.get("embedding"),
                ) for d in data
            ]
            with self._lock:
                self._by_org[org_id] = chunks
            return True
        except Exception as e:
            logger.warning("Bylaw load failed for %s: %s", org_id, e)
            return False


# Module-level singleton so chat_api + tools share the same index.
INDEX = BylawIndex()


# ── Public API ─────────────────────────────────────────────────────────


def lookup(org_id: str, question: str, top_k: int = TOP_K_DEFAULT) -> dict:
    """Top-level API used by the LLM tool layer.

    Returns a dict with:
      status:   "found" | "no_match"
      question: original query
      results:  list of {section, title, text, citation}
      summary:  short caption suitable for the AMENITIES_LIST-style prefix
    """
    chunks = INDEX.retrieve(org_id, question, top_k=top_k)
    if not chunks:
        return {
            "status": "no_match",
            "question": question,
            "results": [],
            "summary": "I don't see a specific bylaw covering this. Please check with your property manager.",
        }
    results = [{
        "section": c.section_number,
        "title": c.section_title,
        "text": c.text,
        "citation": c.citation(),
    } for c in chunks]
    summary = (
        f"Top match: {chunks[0].citation()}. "
        f"Found {len(chunks)} relevant section{'s' if len(chunks) != 1 else ''}."
    )
    return {
        "status": "found",
        "question": question,
        "results": results,
        "summary": summary,
    }


def bootstrap_demo_bylaws(org_id: str = "maple_heights") -> int:
    """Idempotently seed the demo bylaw text for the given org.

    Real deployments overwrite this by uploading the building's actual PDF
    via an admin endpoint (out of AI scope — handled by other team).
    """
    if INDEX.has_org(org_id):
        return INDEX.size(org_id)
    if INDEX.load(org_id):
        return INDEX.size(org_id)
    n = INDEX.ingest_text(org_id, DEMO_BYLAWS_MAPLE_HEIGHTS)
    try:
        INDEX.save(org_id)
    except Exception:
        pass
    return n


# ── Demo bylaws (Canadian condo / strata, English-only) ────────────────


DEMO_BYLAWS_MAPLE_HEIGHTS = """\
Section 1.1  General Application
These bylaws govern all residents, owners, tenants, and guests of Maple
Heights. They are enforceable by the Strata Council and apply uniformly
to every unit. Owners are responsible for the conduct of their tenants
and guests. Violations may result in written warning, fine, and ultimately
revocation of common-area privileges.

Section 1.2  Communication
Official notices are delivered by email and posted in the lobby. Owners
must keep their contact information current with the property manager.
Annual General Meeting (AGM) notices are sent at least 21 days in advance
as required by provincial law.

Section 2.1  Pets — General Rules
Pets are permitted with the following restrictions. A maximum of two
domestic pets per unit (cats, dogs, or one of each). Dogs must be on a
leash at all times in common areas. Owners must clean up after their pets
immediately. Pet registration with the property manager is mandatory and
must be renewed annually with proof of vaccination.

Section 2.2  Pets — Weight and Breed
No dog weighing more than 30 kg may be kept in any unit. Aggressive
breeds (as defined by the City Bylaw) are prohibited. Service animals
under provincial human-rights protections are exempt from weight and
breed restrictions but must still be registered.

Section 3.1  Hardwood Flooring and Floor Coverings
Original units are carpeted. Hardwood, laminate, vinyl plank, or any
hard-surface flooring installation requires written board approval before
work begins. Owners must install a minimum 8 oz/sq yd acoustic underlay
meeting STC-55 / IIC-50 ratings. Failure to comply may require removal
of the installation at the owner's expense. Submit Form A-7 to the
property manager with contractor details and acoustic certification.

Section 4.1  Noise and Quiet Hours
Quiet hours are 11:00 PM to 7:00 AM weekdays and 12:00 AM to 8:00 AM
weekends. During quiet hours, residents must avoid any noise audible in
adjacent units, including loud music, vacuuming, drilling, and
appliances. Repeated violations may result in fines starting at CAD $100.

Section 5.1  Smoking
Smoking of tobacco, cannabis, vaping, or any combustible substance is
prohibited inside individual units, on balconies, in the parking garage,
and within 9 metres of any building entrance. The designated smoking
area is at the south end of the courtyard. Owners may be held liable
for damage caused by smoke residue.

Section 6.1  Balcony Use
Barbecues using propane, charcoal, or open flame are prohibited on all
balconies. Electric grills are permitted. Plants are permitted subject
to weight and drainage rules — water must not drip onto units below.
Storage of bicycles, mattresses, or large items on balconies is not
permitted. Holiday decorations may be displayed for up to 30 days.

Section 7.1  Unit Alterations
Any alteration affecting the structure, plumbing, electrical, or HVAC
systems requires written board approval and may require a professional
engineer's stamp. Cosmetic alterations (paint, wallpaper) inside the
unit do not require approval. Window film, blinds visible from outside,
and any modification to the building exterior are prohibited.

Section 8.1  Parking — Resident Spots
Each unit is assigned one parking spot per the strata plan. Resident
spots may not be sublet, sold separately, or rented to non-residents
without board approval. Vehicles must be in working order and currently
licensed. Abandoned or unregistered vehicles will be towed at the
owner's expense.

Section 8.2  Visitor Parking
Visitor parking is limited to 24 hours per visit. A valid Visitor
Parking Pass, available from the concierge or via the resident app,
must be displayed on the dashboard at all times. Vehicles without a
valid pass may be towed without further notice. Owners may not use
visitor parking for their own daily vehicles.

Section 9.1  Move-In / Move-Out
All moves require an Elevator Booking and a refundable damage deposit
of CAD $500. Bookings must be made at least 7 days in advance through
the property manager or the resident app. Moves are permitted Monday
through Saturday, 9:00 AM to 5:00 PM only. Damage to elevators, hallways,
or common areas during a move is the responsibility of the unit owner.

Section 10.1  Strata Fees and Late Payment
Monthly strata fees are due on the first day of each month. Payments
received after the 15th are subject to a CAD $50 late fee. Accounts
more than 60 days overdue may have common-area privileges (gym, pool,
amenity bookings) suspended until the account is current. Persistent
arrears may result in a lien against the unit per provincial law.

Section 11.1  Common Areas
The gym, pool, party room, library, and other amenities are for
resident and accompanied-guest use only. A maximum of 2 guests per unit
in the gym at any time. Children under 12 must be supervised by an
adult in all amenity areas. Booking required for the party room,
yoga studio, and rooftop terrace.

Section 12.1  Short-Term Rentals
Short-term rentals (under 30 days, including Airbnb, VRBO, and similar
platforms) are prohibited. Any rental must be a minimum 30-day lease
and the property manager must be notified within 7 days of a new tenant
moving in. Owners are responsible for ensuring tenants are aware of and
comply with these bylaws.
"""
