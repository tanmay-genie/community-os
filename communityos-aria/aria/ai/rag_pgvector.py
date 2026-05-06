"""
aria.ai.rag_pgvector — Optional pgvector-backed RAG.

Activated by setting `ARIA_RAG_BACKEND=pgvector`. Requires:
  - Postgres with pgvector extension installed, OR
  - Postgres with the fallback TEXT embedding column (from migration
    5b1667ba2d86 — works but does cosine in Python).

Both modes are transparent to callers. Falls back silently to the in-memory
RAG when DB isn't reachable or the table doesn't exist.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("aria.ai.rag_pgvector")


def _sync_dsn_from_async(url: str) -> str:
    """Convert a SQLAlchemy async URL to a libpq URL psycopg2 understands."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


@dataclass
class PgChunk:
    chunk_id: str
    doc_id: str
    source: str
    title: str
    text: str


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / denom if denom else 0.0


class PgVectorRAG:
    def __init__(self, dsn: str):
        self._dsn = _sync_dsn_from_async(dsn)
        self._has_native_vector = self._detect_vector_ext()
        self._model = None
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning("pgvector RAG: sentence-transformers unavailable — cannot embed (%s)", e)

    def _detect_vector_ext(self) -> bool:
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                return cur.fetchone() is not None
        except Exception:
            return False

    def _embed(self, text: str) -> Optional[list[float]]:
        if not self._model:
            return None
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return [float(x) for x in vec]

    def upsert(self, chunk_id: str, doc_id: str, source: str, title: str, text: str) -> bool:
        emb = self._embed(text)
        if emb is None:
            return False
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                if self._has_native_vector:
                    cur.execute(
                        """
                        INSERT INTO rag_chunks (chunk_id, doc_id, source, title, text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT (chunk_id) DO UPDATE
                        SET text = EXCLUDED.text, embedding = EXCLUDED.embedding
                        """,
                        (chunk_id, doc_id, source, title, text, str(emb)),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO rag_chunks (chunk_id, doc_id, source, title, text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (chunk_id) DO UPDATE
                        SET text = EXCLUDED.text, embedding = EXCLUDED.embedding
                        """,
                        (chunk_id, doc_id, source, title, text, json.dumps(emb)),
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.warning("pgvector upsert failed: %s", e)
            return False

    def retrieve(self, query: str, top_k: int = 3) -> list[PgChunk]:
        emb = self._embed(query)
        if emb is None:
            return []
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                if self._has_native_vector:
                    cur.execute(
                        """
                        SELECT chunk_id, doc_id, source, title, text,
                               1 - (embedding <=> %s::vector) AS similarity
                        FROM rag_chunks
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (str(emb), str(emb), top_k),
                    )
                    rows = cur.fetchall()
                    return [
                        PgChunk(r["chunk_id"], r["doc_id"], r["source"], r["title"], r["text"])
                        for r in rows if r.get("similarity", 0) > 0.25
                    ]
                else:
                    cur.execute("SELECT chunk_id, doc_id, source, title, text, embedding FROM rag_chunks")
                    rows = cur.fetchall()
                    scored: list[tuple[PgChunk, float]] = []
                    for r in rows:
                        try:
                            vec = json.loads(r["embedding"]) if r["embedding"] else None
                        except Exception:
                            vec = None
                        if not vec:
                            continue
                        score = _cosine(emb, vec)
                        if score > 0.25:
                            scored.append(
                                (PgChunk(r["chunk_id"], r["doc_id"], r["source"], r["title"], r["text"]), score)
                            )
                    scored.sort(key=lambda x: x[1], reverse=True)
                    return [c for c, _ in scored[:top_k]]
        except Exception as e:
            logger.warning("pgvector retrieve failed: %s", e)
            return []

    def count(self) -> int:
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM rag_chunks")
                return int(cur.fetchone()[0])
        except Exception:
            return 0


def get_pgvector_backend() -> Optional[PgVectorRAG]:
    """Return a backend only if flag is set AND DB is reachable."""
    if os.getenv("ARIA_RAG_BACKEND", "").lower() != "pgvector":
        return None
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        logger.warning("ARIA_RAG_BACKEND=pgvector but DATABASE_URL unset — falling back")
        return None
    try:
        backend = PgVectorRAG(dsn)
        with psycopg2.connect(backend._dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM rag_chunks LIMIT 1")
            cur.fetchall()
        logger.info("pgvector RAG backend active (native_vector=%s)", backend._has_native_vector)
        return backend
    except Exception as e:
        logger.warning("pgvector RAG disabled — %s", e)
        return None
