"""
aria.ai.intent_classifier — Hybrid embeddings + keyword intent detection.

Strategy:
  1. Fast keyword/regex path (existing) — wins on exact matches, zero cost.
  2. Embeddings fallback: compute embedding of user message, compare to
     per-intent centroid embeddings. Highest cosine similarity wins if above
     threshold. Uses sentence-transformers (optional dep).
  3. LLM tiebreaker (only when embeddings similarity is low/ambiguous):
     cheap Gemini Flash call classifies into one of the known intents.

Graceful degradation: if sentence-transformers isn't installed, falls back
to lexical similarity via TF-IDF-ish bag-of-words scoring.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger("aria.ai.intent_classifier")

INTENT_EXAMPLES: dict[str, list[str]] = {
    "list_society_amenities": [
        "what amenities are available",
        "show me all facilities",
        "what can I book",
        "kya kya available hai",
        "list all amenities",
        "show me everything in the society",
        "what facilities does the society have",
    ],
    "find_amenities_by_type": [
        "show me all gyms",
        "kitne gym hai",
        "list all the pools",
        "all badminton courts",
        "tennis courts available",
        "how many gyms are there",
        "show all halls",
    ],
    "get_amenity_info": [
        "tell me about block a gym",
        "details of the spa",
        "what is in the clubhouse",
        "info on the swimming pool",
        "describe the yoga studio",
    ],
    "show_amenity_slots": [
        "gym slots for tomorrow",
        "when can I book the pool",
        "show me available slots",
        "what time slots are open",
        "block a gym timings tomorrow",
    ],
    "book_amenity": [
        "book the gym for 7pm",
        "reserve clubhouse tomorrow",
        "I want to use the pool at 8am",
        "is the badminton court free",
        "can I book tennis",
        "reserve community hall for sunday",
        "book block a gym at 7am",
    ],
    "cancel_booking": [
        "cancel my booking",
        "I need to cancel the gym reservation",
        "cancel booking ABC12345",
        "please cancel my pool slot",
    ],
    "create_ticket": [
        "AC is not working",
        "ac not working",
        "lift is stuck on 3rd floor",
        "water leakage in bathroom",
        "water leaking",
        "report a plumbing issue",
        "urgent electrical problem",
        "gate intercom is broken",
        "raise a ticket for broken light",
        "maintenance problem issue",
    ],
    "get_society_events": [
        "what events are happening",
        "any events today",
        "show me upcoming activities",
        "what's going on this week",
    ],
    "rsvp_to_event": [
        "sign me up for yoga",
        "rsvp for the society meeting",
        "I want to attend the cricket event",
        "count me in for Holi celebration",
    ],
    "check_dues": [
        "do I have any pending dues",
        "check my maintenance balance",
        "how much do I owe",
        "is my rent paid",
    ],
    "pay_dues": [
        "pay my maintenance",
        "I want to pay 4500 rupees",
        "clear my dues",
        "settle the balance",
    ],
    "get_notices": [
        "any new notices",
        "show society notices",
        "new notice announcement",
        "show society announcements",
        "latest circulars notices",
        "what's new in the society notice",
    ],
    "get_society_insights": [
        "society summary report",
        "community health overview",
        "give me a status report",
        "how's the society doing",
    ],
    "get_pending_escalations": [
        "pending escalations",
        "what needs my approval",
        "escalation queue",
        "show me approvals",
    ],
    "approve_escalation": [
        "approve escalation ESC-001",
        "green light that task",
        "approve it",
    ],
    "deny_escalation": [
        "deny escalation",
        "reject that task",
        "deny it",
    ],
    "generate_announcement": [
        "draft an announcement about water outage",
        "write a notice for the society",
        "create a circular",
    ],
    "moderate_content": [
        "check this message for violations",
        "moderate this post",
        "is this appropriate",
    ],
}

AMBIGUITY_THRESHOLD = 0.40
CLEAR_MATCH_THRESHOLD = 0.65
ADMIN_INTENTS = {
    "get_society_insights", "get_pending_escalations", "approve_escalation",
    "deny_escalation", "generate_announcement", "moderate_content",
}


@dataclass
class IntentPrediction:
    intent: str | None
    confidence: float
    method: str
    alternatives: list[tuple[str, float]]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _vectorize(text: str) -> Counter:
    return Counter(_tokenize(text))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / denom if denom else 0.0


class _LexicalClassifier:
    def __init__(self):
        self.example_vecs: dict[str, list[Counter]] = {}
        for intent, examples in INTENT_EXAMPLES.items():
            self.example_vecs[intent] = [_vectorize(ex) for ex in examples]

    def classify(self, message: str, role: str = "member") -> IntentPrediction:
        vec = _vectorize(message)
        scores: list[tuple[str, float]] = []
        for intent, example_vecs in self.example_vecs.items():
            if intent in ADMIN_INTENTS and role != "admin":
                continue
            max_sim = max((_cosine(vec, ev) for ev in example_vecs), default=0.0)
            scores.append((intent, max_sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        if not scores:
            return IntentPrediction(None, 0.0, "lexical", [])
        top_intent, top_score = scores[0]
        return IntentPrediction(
            intent=top_intent if top_score >= AMBIGUITY_THRESHOLD else None,
            confidence=top_score,
            method="lexical",
            alternatives=scores[:3],
        )


class _EmbeddingsClassifier:
    def __init__(self):
        self._model = None
        self._centroids: dict[str, list[float]] = {}
        self._available = False
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            for intent, examples in INTENT_EXAMPLES.items():
                embs = self._model.encode(examples, normalize_embeddings=True)
                centroid = embs.mean(axis=0)
                norm = math.sqrt(sum(float(x) * float(x) for x in centroid))
                self._centroids[intent] = [float(x) / norm for x in centroid] if norm else [float(x) for x in centroid]
            self._available = True
            logger.info("Embeddings intent classifier loaded (MiniLM-L6-v2)")
        except Exception as e:
            logger.info("sentence-transformers unavailable, using lexical classifier: %s", e)

    @property
    def available(self) -> bool:
        return self._available

    def classify(self, message: str, role: str = "member") -> IntentPrediction:
        if not self._available:
            return IntentPrediction(None, 0.0, "embeddings-unavailable", [])
        try:
            emb = self._model.encode([message], normalize_embeddings=True)[0]
            emb_list = [float(x) for x in emb]
            scores: list[tuple[str, float]] = []
            for intent, centroid in self._centroids.items():
                if intent in ADMIN_INTENTS and role != "admin":
                    continue
                sim = sum(a * b for a, b in zip(emb_list, centroid))
                scores.append((intent, sim))
            scores.sort(key=lambda x: x[1], reverse=True)
            if not scores:
                return IntentPrediction(None, 0.0, "embeddings", [])
            top_intent, top_score = scores[0]
            return IntentPrediction(
                intent=top_intent if top_score >= AMBIGUITY_THRESHOLD else None,
                confidence=top_score,
                method="embeddings",
                alternatives=scores[:3],
            )
        except Exception as e:
            logger.warning("Embedding classify failed: %s", e)
            return IntentPrediction(None, 0.0, "embeddings-error", [])


_embeddings = _EmbeddingsClassifier()
_lexical = _LexicalClassifier()


def classify_intent(message: str, role: str = "member") -> IntentPrediction:
    """
    Classify message -> intent. Tries embeddings first, falls back to lexical.
    Returns IntentPrediction with confidence + alternatives.
    """
    if _embeddings.available:
        pred = _embeddings.classify(message, role)
        if pred.intent and pred.confidence >= CLEAR_MATCH_THRESHOLD:
            return pred
        lex = _lexical.classify(message, role)
        if lex.confidence > pred.confidence:
            return lex
        return pred
    return _lexical.classify(message, role)
