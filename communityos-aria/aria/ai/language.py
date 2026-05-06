"""
aria.ai.language — Language detection (English / Hindi / Hinglish).

Lightweight heuristic detector. Returns a language hint + tone instruction
that gets appended to the system prompt so the LLM mirrors the user's
language naturally (Devanagari replies for Hindi, romanized Hindi mixed
with English for Hinglish).
"""
from __future__ import annotations

import re

HINDI_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
HINGLISH_MARKERS = {
    "kya", "hai", "kaise", "nahi", "nhi", "haan", "haa", "bhi", "kar",
    "kro", "kara", "karo", "chahiye", "chahie", "tha", "tum", "mera", "meri",
    "humara", "hamara", "apna", "apne", "kuch", "koi", "yaar", "bhai",
    "accha", "acha", "theek", "thik", "abhi", "jaldi", "problem", "urgent",
    "mere", "ko", "hona", "raha", "rahi", "rahe", "karna", "dena", "lena",
    "bata", "bataiye", "bolo", "bhej", "dekho", "samjha", "samjhi",
}


def detect_language(message: str) -> str:
    """Return 'hindi' | 'hinglish' | 'english'."""
    if not message:
        return "english"
    if HINDI_DEVANAGARI.search(message):
        return "hindi"
    tokens = re.findall(r"[a-zA-Z]+", message.lower())
    if not tokens:
        return "english"
    hindi_token_hits = sum(1 for t in tokens if t in HINGLISH_MARKERS)
    ratio = hindi_token_hits / len(tokens)
    if ratio >= 0.15:
        return "hinglish"
    return "english"


def language_hint(lang: str) -> str:
    if lang == "hindi":
        return ("भाषा निर्देश: उपयोगकर्ता ने हिंदी में लिखा है। "
                "कृपया देवनागरी में संक्षिप्त, मैत्रीपूर्ण उत्तर दें। तकनीकी शब्द अंग्रेज़ी में रख सकते हैं।")
    if lang == "hinglish":
        return ("Language instruction: The user mixed Hindi + English (Hinglish). "
                "Reply in the same casual Hinglish style — roman-script Hindi words "
                "mixed with English is perfect. Don't switch to pure English or pure Hindi.")
    return ""
