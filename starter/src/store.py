"""Store and search vectors in PostgreSQL + pgvector.

One table holds every index; `strategy` names the index (e.g. "fixed500o50",
"article1500"). Strategy C reuses the B index and only adds a filter, so the
B–C comparison changes nothing but the filter.

Search is exact (sequential scan, no ANN index) with cosine distance `<=>`;
score = 1 - cosine distance. At ~2k rows exact search is fast and makes
filtered results deterministic (no ANN recall loss under filtering).
"""
from __future__ import annotations

import json
import math
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

TABLE = "rag_chunks"
# Metadata keys that may be used as filters, mapped to real columns (whitelist:
# user input never becomes SQL identifiers).
FILTER_COLUMNS = {"document_id": "document_id", "phan": "phan", "chuong": "chuong",
                  "muc": "muc", "dieu": "dieu"}


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL missing: copy starter/.env.example to starter/.env")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError(f"invalid embedding dimensions: {dimensions!r}")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        """Create the table if needed and refuse a table built for other dims."""
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy        text        NOT NULL,
                    chunk_id        text        NOT NULL,
                    document_id     text        NOT NULL,
                    source          text        NOT NULL,
                    page            integer     NOT NULL,
                    pages           integer[]   NOT NULL,
                    phan            text,
                    chuong          text,
                    muc             text,
                    dieu            text,
                    text            text        NOT NULL,
                    metadata        jsonb       NOT NULL,
                    content_hash    text        NOT NULL,
                    embedding_model text        NOT NULL,
                    embedding       vector({self.dimensions}) NOT NULL,
                    updated_at      timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_filter_idx ON {TABLE} (strategy, chuong)")
            row = conn.execute(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid = %s::regclass AND a.attname = 'embedding'", (TABLE,)).fetchone()
            if row and row[0] != f"vector({self.dimensions})":
                raise RuntimeError(f"{TABLE}.embedding is {row[0]}, model needs vector({self.dimensions}); "
                                   "use a new table instead of mixing models")

    def existing_hashes(self, strategy: str) -> dict[str, tuple[str, str]]:
        """{chunk_id: (content_hash, embedding_model)} already stored for an index."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT chunk_id, content_hash, embedding_model FROM {TABLE} "
                                "WHERE strategy = %s", (strategy,)).fetchall()
        return {cid: (h, m) for cid, h, m in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               embedding_model: str = "") -> int:
        """Insert or update rows keyed by (strategy, chunk_id); never duplicates.

        Only writes the given chunks (unchanged chunks may be skipped by the
        caller to save embedding cost). Removing obsolete chunks after a source
        change is done by prune(), which needs the full current id list.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in one upsert batch")
        for chunk, vector in zip(chunks, vectors):
            if len(vector) != self.dimensions:
                raise ValueError(f"{chunk.chunk_id}: vector has {len(vector)} dims, expected {self.dimensions}")
            if not all(math.isfinite(x) for x in vector):
                raise ValueError(f"{chunk.chunk_id}: non-finite vector")
        rows = []
        for chunk, vector in zip(chunks, vectors):
            meta = chunk.metadata
            rows.append((strategy, chunk.chunk_id, chunk.document_id, chunk.source, chunk.page,
                         meta.get("pages") or [chunk.page], meta.get("phan"), meta.get("chuong"),
                         meta.get("muc"), meta.get("dieu"), chunk.text,
                         Jsonb(json.loads(json.dumps(meta, ensure_ascii=False, default=str))),
                         meta["content_hash"], embedding_model, _vector_literal(vector)))
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, pages, phan, chuong,
                                     muc, dieu, text, metadata, content_hash, embedding_model, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                    pages = EXCLUDED.pages, phan = EXCLUDED.phan, chuong = EXCLUDED.chuong,
                    muc = EXCLUDED.muc, dieu = EXCLUDED.dieu, text = EXCLUDED.text,
                    metadata = EXCLUDED.metadata, content_hash = EXCLUDED.content_hash,
                    embedding_model = EXCLUDED.embedding_model, embedding = EXCLUDED.embedding,
                    updated_at = now()""", rows)
        return len(rows)

    def prune(self, strategy: str, document_id: str, keep_chunk_ids: list[str]) -> int:
        """Delete chunks of a document that are no longer produced (source changed)."""
        with self._connect() as conn:
            cur = conn.execute(f"DELETE FROM {TABLE} WHERE strategy = %s AND document_id = %s "
                               "AND NOT (chunk_id = ANY(%s))", (strategy, document_id, keep_chunk_ids))
            return cur.rowcount

    def count(self, strategy: str) -> dict[str, int]:
        with self._connect() as conn:
            total, distinct = conn.execute(
                f"SELECT count(*), count(DISTINCT chunk_id) FROM {TABLE} WHERE strategy = %s",
                (strategy,)).fetchone()
        return {"rows": total, "distinct_chunk_ids": distinct}

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Filter in SQL (whitelisted columns, parameterized values), rank by cosine."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            column = FILTER_COLUMNS.get(key)
            if column is None:
                raise ValueError(f"filter on {key!r} not allowed; allowed: {sorted(FILTER_COLUMNS)}")
            if isinstance(value, (list, tuple)):
                where.append(f"{column} = ANY(%s)")
                params.append(list(map(str, value)))
            else:
                where.append(f"{column} = %s")
                params.append(str(value))
        qv = _vector_literal(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, pages, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM {TABLE} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, top_k]).fetchall()
        return [{"rank": i + 1, "chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3],
                 "pages": r[4], "text": r[5], "metadata": r[6], "score": float(r[7])}
                for i, r in enumerate(rows)]
