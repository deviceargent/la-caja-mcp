from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


ROOT = Path(os.environ.get("LA_CAJA_DATA", "./data"))
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "caja.db"

mcp = FastMCP("La Caja")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
        )"""
    )
    conn.commit()
    return conn


def entity_exists(conn: sqlite3.Connection, entity_id: str) -> bool:
    return conn.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone() is not None


def event(entity_id: str, actor: str, kind: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    conn = db()
    if not entity_exists(conn, entity_id):
        conn.close()
        return {"error": "entity_not_found", "entity_id": entity_id}
    item = {
        "id": str(uuid.uuid4()),
        "entity_id": entity_id,
        "actor": actor,
        "kind": kind,
        "content": content,
        "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        "created_at": now(),
    }
    conn.execute(
        "INSERT INTO events VALUES (:id,:entity_id,:actor,:kind,:content,:metadata,:created_at)",
        item,
    )
    conn.execute("UPDATE entities SET updated_at=? WHERE id=?", (item["created_at"], entity_id))
    conn.commit()
    conn.close()
    return item


@mcp.tool()
def get_state(actor: str = "unknown") -> dict[str, Any]:
    """Return the complete research state without silently truncating history."""
    conn = db()
    entities = [dict(r) for r in conn.execute("SELECT * FROM entities ORDER BY updated_at DESC").fetchall()]
    events = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY created_at ASC").fetchall()]
    conn.close()
    return {"actor": actor, "entities": entities, "recent_events": events}


@mcp.tool()
def get_entity(entity_id: str, actor: str = "unknown") -> dict[str, Any]:
    """Return one entity and its complete deliberation history."""
    conn = db()
    row = conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE entity_id=? ORDER BY created_at", (entity_id,)
    ).fetchall()]
    conn.close()
    if row is None:
        return {"error": "entity_not_found", "entity_id": entity_id}
    return {"actor": actor, "entity": dict(row), "history": events}


@mcp.tool()
def search_context(query: str, actor: str = "unknown", limit: int = 20) -> dict[str, Any]:
    """Search entity metadata and deliberation event content by SQLite text matching."""
    pattern = f"%{query}%"
    conn = db()
    entities = [dict(r) for r in conn.execute(
        "SELECT * FROM entities WHERE title LIKE ? OR type LIKE ? ORDER BY updated_at DESC LIMIT ?",
        (pattern, pattern, limit),
    ).fetchall()]
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE content LIKE ? OR kind LIKE ? OR actor LIKE ? ORDER BY created_at DESC LIMIT ?",
        (pattern, pattern, pattern, limit),
    ).fetchall()]
    conn.close()
    return {"actor": actor, "query": query, "entities": entities, "events": events}


@mcp.tool()
def propose(title: str, content: str, actor: str, entity_type: str = "proposal") -> dict[str, Any]:
    """Create a new proposal/entity and record its originating argument."""
    entity_id = str(uuid.uuid4())
    timestamp = now()
    conn = db()
    conn.execute(
        "INSERT INTO entities VALUES (?,?,?,?,?,?)",
        (entity_id, entity_type, title, "candidate", timestamp, timestamp),
    )
    conn.commit()
    conn.close()
    return {
        "entity": {"id": entity_id, "type": entity_type, "title": title, "status": "candidate"},
        "event": event(entity_id, actor, "proposal", content),
    }


@mcp.tool()
def challenge(entity_id: str, content: str, actor: str, targets: list[str] | None = None) -> dict[str, Any]:
    """Record an adversarial objection without deleting or replacing prior reasoning."""
    return event(entity_id, actor, "challenge", content, {"targets": targets or []})


@mcp.tool()
def update_entity(entity_id: str, status: str, content: str, actor: str) -> dict[str, Any]:
    """Change an entity's status while preserving the reason as an immutable event."""
    allowed = {"candidate", "disputed", "conditional", "consensus", "rejected", "superseded", "unresolved"}
    if status not in allowed:
        return {"error": "invalid_status", "allowed": sorted(allowed)}
    conn = db()
    if not entity_exists(conn, entity_id):
        conn.close()
        return {"error": "entity_not_found", "entity_id": entity_id}
    timestamp = now()
    conn.execute("UPDATE entities SET status=?,updated_at=? WHERE id=?", (status, timestamp, entity_id))
    conn.commit()
    conn.close()
    return event(entity_id, actor, "status_change", content, {"status": status})


@mcp.tool()
def publish_evidence(entity_id: str, source: str, claim: str, actor: str, notes: str = "") -> dict[str, Any]:
    """Attach externally researched evidence to an entity."""
    return event(entity_id, actor, "evidence", claim, {"source": source, "notes": notes})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
