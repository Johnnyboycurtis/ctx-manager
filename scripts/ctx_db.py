#!/usr/bin/env python3
"""
Zero-dependency SQLite + FTS5 context store for ctx-manager.
Manages digests, repo micro-skills, file/symbol index, and command/error logs.
"""
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join(".agents", "context", "ctx.db")


def get_db_path(db_path: str | None = None) -> str:
    """Resolve the SQLite database path from argument, env, or default."""
    return db_path or os.environ.get("CTX_DB_PATH") or DEFAULT_DB_PATH


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection to the context database, creating parent dirs if needed."""
    path = get_db_path(db_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | None = None) -> str:
    """Initialize all tables and FTS5 indexes if they do not exist."""
    path = get_db_path(db_path)
    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_type TEXT DEFAULT 'note',
                file_path TEXT UNIQUE,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS digests_fts USING fts5(
                title,
                source_type,
                content,
                content='digests',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS digests_ai AFTER INSERT ON digests BEGIN
                INSERT INTO digests_fts(rowid, title, source_type, content)
                VALUES (new.id, new.title, new.source_type, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS digests_ad AFTER DELETE ON digests BEGIN
                INSERT INTO digests_fts(digests_fts, rowid, title, source_type, content)
                VALUES ('delete', old.id, old.title, old.source_type, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS digests_au AFTER UPDATE ON digests BEGIN
                INSERT INTO digests_fts(digests_fts, rowid, title, source_type, content)
                VALUES ('delete', old.id, old.title, old.source_type, old.content);
                INSERT INTO digests_fts(rowid, title, source_type, content)
                VALUES (new.id, new.title, new.source_type, new.content);
            END;

            CREATE TABLE IF NOT EXISTS micro_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL DEFAULT 'general',
                key TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL UNIQUE,
                symbols TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS command_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                exit_code INTEGER NOT NULL,
                error_signature TEXT DEFAULT '',
                archive_path TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
    return path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert_digest(
    title: str,
    content: str,
    source_type: str = "note",
    file_path: str | None = None,
    db_path: str | None = None,
) -> int:
    """Insert or update a digest entry by file_path (or insert new if no file_path)."""
    init_db(db_path)
    now = _now()
    with connect(db_path) as conn:
        if file_path:
            existing = conn.execute(
                "SELECT id FROM digests WHERE file_path = ?", (file_path,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE digests SET title = ?, source_type = ?, content = ?, created_at = ? WHERE id = ?",
                    (title, source_type, content, now, existing["id"]),
                )
                return existing["id"]
        cur = conn.execute(
            "INSERT INTO digests (title, source_type, file_path, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, source_type, file_path, content, now),
        )
        return cur.lastrowid


def search_digests(query: str, limit: int = 5, db_path: str | None = None) -> list[dict]:
    """Search digests using FTS5 BM25 ranking and return matching snippets."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                d.id,
                d.title,
                d.source_type,
                d.file_path,
                d.created_at,
                snippet(digests_fts, 2, '[', ']', '...', 24) AS snippet,
                bm25(digests_fts) AS score
            FROM digests_fts
            JOIN digests d ON d.id = digests_fts.rowid
            WHERE digests_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def add_micro_skill(
    key: str, value: str, category: str = "general", db_path: str | None = None
) -> None:
    """Store or update a repo-specific micro-skill or quirk."""
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO micro_skills (category, key, value, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                category = excluded.category,
                value = excluded.value,
                created_at = excluded.created_at
            """,
            (category, key, value, _now()),
        )


def upsert_file_index(
    file_path: str, symbols: str = "", summary: str = "", db_path: str | None = None
) -> None:
    """Store or update a file's symbol list and 1-line summary."""
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO file_index (file_path, symbols, summary, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                symbols = excluded.symbols,
                summary = excluded.summary,
                updated_at = excluded.updated_at
            """,
            (file_path, symbols, summary, _now()),
        )


def log_command(
    command: str,
    exit_code: int,
    error_signature: str = "",
    archive_path: str = "",
    db_path: str | None = None,
) -> None:
    """Record a command execution for loop detection and history."""
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO command_log (command, exit_code, error_signature, archive_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (command, exit_code, error_signature, archive_path, _now()),
        )


def prune_command_logs(days: int = 10, db_path: str | None = None) -> int:
    """Delete command_log entries older than `days` days. Returns rows deleted."""
    path = get_db_path(db_path)
    if not os.path.isfile(path):
        return 0
    with connect(path) as conn:
        cur = conn.execute(
            "DELETE FROM command_log WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        return cur.rowcount
