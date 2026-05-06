"""
aria.ai.rag — Retrieval-Augmented Generation over society documents.

Indexes society bye-laws, FAQ, committee decisions, notices into an
in-process vector store. Retrieves top-K chunks relevant to user query
and injects them into the system prompt as grounded context.

Falls back to BM25-ish keyword retrieval if sentence-transformers is
unavailable. Persists embeddings to disk so rebuild is skipped on restart.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger("aria.ai.rag")

CHUNK_SIZE_WORDS = 120
CHUNK_OVERLAP_WORDS = 30
TOP_K_DEFAULT = 3
INDEX_DIR = Path("aria/resources/rag_index")


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    source: str
    title: str
    text: str
    embedding: list[float] | None = None


def _chunk_text(text: str, size: int = CHUNK_SIZE_WORDS, overlap: int = CHUNK_OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    step = max(1, size - overlap)
    for i in range(0, len(words), step):
        piece = words[i : i + size]
        if piece:
            chunks.append(" ".join(piece))
        if i + size >= len(words):
            break
    return chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / denom if denom else 0.0


class RAGIndex:
    def __init__(self):
        self._chunks: list[Chunk] = []
        self._model = None
        self._embeddings_available = False
        self._lock = Lock()
        self._load_model()

    def _load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._embeddings_available = True
            logger.info("RAG: sentence-transformers loaded")
        except Exception as e:
            logger.info("RAG: using lexical fallback (%s)", e)

    def add_document(self, doc_id: str, source: str, title: str, text: str) -> int:
        chunks_text = _chunk_text(text)
        new_chunks: list[Chunk] = []
        for i, piece in enumerate(chunks_text):
            cid = hashlib.md5(f"{doc_id}:{i}:{piece[:40]}".encode()).hexdigest()[:12]
            new_chunks.append(Chunk(doc_id=doc_id, chunk_id=cid, source=source, title=title, text=piece))

        if self._embeddings_available and new_chunks:
            try:
                embs = self._model.encode([c.text for c in new_chunks], normalize_embeddings=True)
                for c, e in zip(new_chunks, embs):
                    c.embedding = [float(x) for x in e]
            except Exception as ex:
                logger.warning("Embedding failed: %s", ex)

        with self._lock:
            self._chunks.extend(new_chunks)
        return len(new_chunks)

    def retrieve(self, query: str, top_k: int = TOP_K_DEFAULT) -> list[Chunk]:
        if not query or not self._chunks:
            return []

        if self._embeddings_available:
            try:
                q_emb = [float(x) for x in self._model.encode([query], normalize_embeddings=True)[0]]
                scored = [
                    (c, _cosine(q_emb, c.embedding))
                    for c in self._chunks if c.embedding
                ]
                scored.sort(key=lambda x: x[1], reverse=True)
                return [c for c, score in scored[:top_k] if score > 0.25]
            except Exception as e:
                logger.warning("Embedding retrieval failed: %s", e)

        q_tokens = Counter(_tokenize(query))
        scored: list[tuple[Chunk, float]] = []
        for c in self._chunks:
            c_tokens = Counter(_tokenize(c.text))
            common = set(q_tokens) & set(c_tokens)
            score = sum(q_tokens[t] * c_tokens[t] for t in common) / max(1, len(c_tokens))
            if score > 0:
                scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_k]]

    def save(self, path: Path = INDEX_DIR) -> None:
        path.mkdir(parents=True, exist_ok=True)
        data = [
            {"doc_id": c.doc_id, "chunk_id": c.chunk_id, "source": c.source,
             "title": c.title, "text": c.text, "embedding": c.embedding}
            for c in self._chunks
        ]
        (path / "chunks.json").write_text(json.dumps(data), encoding="utf-8")
        logger.info("RAG index saved: %d chunks", len(data))

    def load(self, path: Path = INDEX_DIR) -> bool:
        fp = path / "chunks.json"
        if not fp.exists():
            return False
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            self._chunks = [
                Chunk(doc_id=d["doc_id"], chunk_id=d["chunk_id"], source=d["source"],
                      title=d["title"], text=d["text"], embedding=d.get("embedding"))
                for d in data
            ]
            logger.info("RAG index loaded: %d chunks", len(self._chunks))
            return True
        except Exception as e:
            logger.warning("RAG load failed: %s", e)
            return False

    @property
    def size(self) -> int:
        return len(self._chunks)


rag = RAGIndex()


DEFAULT_SOCIETY_DOCS = [
    {
        "doc_id": "bylaws_bookings",
        "source": "society_bylaws.md",
        "title": "Amenity Booking Rules",
        "text": (
            "Residents may book amenities up to 7 days in advance. Gym is open 6 AM to 10 PM. "
            "Pool is open 7 AM to 9 PM. Clubhouse and community hall may be booked for up to 4 hours. "
            "Only one booking per resident per amenity per day. Bookings can be cancelled up to 2 hours "
            "before the slot. No-shows result in a one-week suspension. Guest entries require prior "
            "registration at the security gate."
        ),
    },
    {
        "doc_id": "bylaws_dues",
        "source": "society_bylaws.md",
        "title": "Maintenance and Dues Policy",
        "text": (
            "Monthly maintenance is due on the 5th of every month. A late fee of 2 percent per month "
            "applies after the 15th. Parking charges are Rs.1500 per month per vehicle. Dues above "
            "Rs.10,000 trigger restricted access to amenity bookings until paid. Payment methods "
            "accepted: UPI, bank transfer, cheque. Receipts are emailed within 24 hours."
        ),
    },
    {
        "doc_id": "faq_tickets",
        "source": "faq.md",
        "title": "Maintenance Ticket FAQ",
        "text": (
            "To raise a maintenance ticket, use ARIA or the resident portal. Urgent issues (water "
            "flooding, gas leak, fire, lift trapped) trigger immediate response within 15 minutes. "
            "Normal tickets are acknowledged within 2 hours. You can track ticket status through ARIA "
            "by asking 'status of my ticket'. Escalations are handled by the Committee after 24 hours."
        ),
    },
    {
        "doc_id": "committee_decisions_2026",
        "source": "committee_minutes.md",
        "title": "Recent Committee Decisions",
        "text": (
            "Visitor parking limited to 4 hours effective 2026-04-01. Pet registration mandatory from "
            "2026-05-01. New waste segregation policy in effect. Holi and Diwali events continue on "
            "rotating venue schedule. Terrace garden maintenance contract renewed with GreenSpace Pvt "
            "Ltd for 1 year."
        ),
    },
    {
        "doc_id": "emergency_contacts",
        "source": "emergency.md",
        "title": "Emergency Contacts",
        "text": (
            "Fire: 101. Police: 100. Ambulance: 108. Society security: main gate intercom. "
            "Facility manager: after 8 PM, please use the emergency button in each tower's lobby. "
            "For medical emergencies, contact the resident doctor on-call listed on the notice board."
        ),
    },
]


_pgvector_backend = None
try:
    from aria.ai.rag_pgvector import get_pgvector_backend
    _pgvector_backend = get_pgvector_backend()
except Exception as e:
    logger.debug("pgvector backend unavailable: %s", e)


def bootstrap_default_index() -> int:
    """Load or build the default society knowledge index."""
    # If pgvector is active, seed it once with the default docs
    if _pgvector_backend is not None and _pgvector_backend.count() == 0:
        for doc in DEFAULT_SOCIETY_DOCS:
            chunks_text = _chunk_text(doc["text"])
            for i, piece in enumerate(chunks_text):
                cid = hashlib.md5(f"{doc['doc_id']}:{i}:{piece[:40]}".encode()).hexdigest()[:12]
                _pgvector_backend.upsert(cid, doc["doc_id"], doc["source"], doc["title"], piece)
        logger.info("pgvector RAG seeded: %d chunks", _pgvector_backend.count())

    # In-memory path (always built — acts as fallback if pgvector retrieval fails)
    if rag.size > 0:
        return rag.size
    if rag.load():
        return rag.size
    total = 0
    for doc in DEFAULT_SOCIETY_DOCS:
        total += rag.add_document(doc["doc_id"], doc["source"], doc["title"], doc["text"])
    try:
        rag.save()
    except Exception as e:
        logger.info("RAG save skipped: %s", e)
    return total


def retrieve_context(query: str, top_k: int = TOP_K_DEFAULT) -> str:
    """Return formatted context string for a query, or empty string."""
    chunks = None
    if _pgvector_backend is not None:
        pg_chunks = _pgvector_backend.retrieve(query, top_k=top_k)
        if pg_chunks:
            chunks = pg_chunks
    if not chunks:
        chunks = rag.retrieve(query, top_k=top_k)
    if not chunks:
        return ""
    lines = ["--- RELEVANT SOCIETY CONTEXT ---"]
    for c in chunks:
        lines.append(f"[{c.title} — {c.source}]\n{c.text}")
    lines.append("--- END CONTEXT ---")
    return "\n".join(lines)
