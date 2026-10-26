"""Runbook ingestion and semantic search with pgvector.

Each markdown runbook (YAML front matter + ``##`` sections) is split into one chunk per section, embedded
locally, and stored in ``knowledge.runbook_chunks``. Search ranks chunks by cosine distance and returns the
best runbooks with their matching section and allowlisted actions.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml
from mcp.server.mcpserver.exceptions import ToolError
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from oncall_common.embeddings import Embedder

RUNBOOK_DIR = Path(os.environ.get("RUNBOOKS_DIR", Path(__file__).resolve().parents[3] / "runbooks"))
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Runbook:
    id: str
    title: str
    categories: list[str]
    services: list[str]
    actions: list[str]
    body: str

    def sections(self) -> list[tuple[str, str]]:
        """(heading, text) for every ``##`` section; the preamble is skipped."""
        parts = re.split(r"^## +(.+)$", self.body, flags=re.MULTILINE)
        return [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def parse_runbook(text: str) -> Runbook:
    match = _FRONT_MATTER.match(text.replace("\r\n", "\n"))
    if not match:
        raise ValueError("runbook must start with YAML front matter")
    meta = yaml.safe_load(match.group(1))
    for key in ("id", "title", "categories", "actions"):
        if key not in meta:
            raise ValueError(f"runbook front matter missing '{key}'")
    return Runbook(
        meta["id"],
        meta["title"],
        list(meta["categories"]),
        list(meta.get("services", [])),
        list(meta["actions"]),
        match.group(2).strip(),
    )


def load_runbooks(directory: Path = RUNBOOK_DIR) -> list[Runbook]:
    return [parse_runbook(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.md"))]


def _corpus_hash(runbooks: list[Runbook], model: str) -> str:
    digest = hashlib.sha256(model.encode())
    for rb in runbooks:
        digest.update(rb.id.encode())
        digest.update(rb.body.encode())
        digest.update(",".join(rb.actions).encode())
    return digest.hexdigest()


def ingest_runbooks(conn: psycopg.Connection, embedder: Embedder, directory: Path = RUNBOOK_DIR) -> int:
    """(Re)index runbooks if the corpus or embedding model changed. Returns the number of chunks indexed."""
    register_vector(conn)
    runbooks = load_runbooks(directory)
    corpus_hash = _corpus_hash(runbooks, embedder.model_name)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT content_hash FROM knowledge.runbooks")
        existing = {r["content_hash"] for r in cur.fetchall()}
        if existing == {corpus_hash}:
            cur.execute("SELECT count(*) AS n FROM knowledge.runbook_chunks")
            return cur.fetchone()["n"]

        chunks = [(rb, heading, text) for rb in runbooks for heading, text in rb.sections()]
        vectors = embedder.embed([f"{rb.title}. {heading}. {text}" for rb, heading, text in chunks])
        cur.execute("DELETE FROM knowledge.runbooks")  # cascades to chunks
        for rb in runbooks:
            cur.execute(
                "INSERT INTO knowledge.runbooks (runbook_id, title, categories, services, actions, body, content_hash)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    rb.id,
                    rb.title,
                    Jsonb(rb.categories),
                    Jsonb(rb.services),
                    Jsonb(rb.actions),
                    rb.body,
                    corpus_hash,
                ),
            )
        for (rb, heading, text), vector in zip(chunks, vectors, strict=True):
            cur.execute(
                "INSERT INTO knowledge.runbook_chunks (runbook_id, title, section, content, embedding, model)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (rb.id, rb.title, heading, text, vector, embedder.model_name),
            )
    conn.commit()
    return len(chunks)


def search_runbooks(
    conn: psycopg.Connection, embedder: Embedder, *, query: str, k: int = 3
) -> dict[str, Any]:
    if not query.strip():
        raise ToolError("query must not be empty")
    if not 1 <= k <= 10:
        raise ToolError("k must be between 1 and 10")
    register_vector(conn)
    vector = embedder.embed([query])[0]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.runbook_id, c.title, c.section, c.content, 1 - (c.embedding <=> %s) AS score, r.actions,
                   r.categories
            FROM knowledge.runbook_chunks c JOIN knowledge.runbooks r USING (runbook_id)
            ORDER BY c.embedding <=> %s
            LIMIT %s
            """,
            (vector, vector, k * 4),
        )
        rows = cur.fetchall()
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["runbook_id"] not in best:
            best[r["runbook_id"]] = {
                "runbook_id": r["runbook_id"],
                "title": r["title"],
                "score": round(float(r["score"]), 4),
                "matched_section": r["section"],
                "snippet": r["content"][:400],
                "categories": r["categories"],
                "allowed_actions": r["actions"],
            }
    return {"query": query, "results": list(best.values())[:k]}


def get_runbook(conn: psycopg.Connection, *, runbook_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM knowledge.runbooks WHERE runbook_id = %s", [runbook_id])
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT runbook_id FROM knowledge.runbooks ORDER BY runbook_id")
            ids = [r["runbook_id"] for r in cur.fetchall()]
            raise ToolError(f"Unknown runbook '{runbook_id}'. Available: {', '.join(ids)}")
    return {
        "runbook_id": row["runbook_id"],
        "title": row["title"],
        "categories": row["categories"],
        "services": row["services"],
        "allowed_actions": row["actions"],
        "markdown": row["body"],
    }
