"""Migration runner and version tracking for AIRA SQLite database."""

import os
import re
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.config import AIRA_DB_PATH

MIGRATIONS_DIR = Path(__file__).resolve().parent

CREATE_SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    checksum TEXT NOT NULL
);
"""


class MigrationError(Exception):
    """Base exception for database migrations."""
    pass


class MigrationIntegrityError(MigrationError):
    """Raised when an applied migration file has been tampered with or checksum differs."""
    pass


class MigrationExecutionError(MigrationError):
    """Raised when a migration fails to execute."""
    pass


@dataclass
class Migration:
    version: int
    name: str
    file_path: Path
    checksum: str
    sql: str


def compute_checksum(content: str) -> str:
    """Computes a canonical SHA-256 checksum ignoring leading/trailing whitespace and CRLF."""
    normalized = content.replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def split_sql_statements(sql: str) -> List[str]:
    """Splits SQL script into individual executable statements without executing executescript.

    Preserves quotes, comments, and blocks.
    """
    statements = []
    current: List[str] = []
    in_single_quote = False
    in_double_quote = False

    lines = sql.splitlines()
    for line in lines:
        stripped = line.strip()
        # Skip pure comment lines
        if stripped.startswith("--"):
            continue

        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'" and not in_double_quote:
                # Handle escaping ''
                if in_single_quote and i + 1 < len(line) and line[i + 1] == "'":
                    current.append("''")
                    i += 2
                    continue
                in_single_quote = not in_single_quote
            elif ch == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif ch == ";" and not in_single_quote and not in_double_quote:
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += 1
                continue

            current.append(ch)
            i += 1

        current.append("\n")

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


class MigrationRunner:
    def __init__(self, db_path: str = AIRA_DB_PATH, migrations_dir: Path = MIGRATIONS_DIR):
        self.db_path = str(db_path)
        self.migrations_dir = Path(migrations_dir)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        """Ensures the schema_migrations tracking table exists."""
        conn.execute(CREATE_SCHEMA_MIGRATIONS_SQL)
        conn.commit()

    def discover_migrations(self) -> List[Migration]:
        """Discovers and parses migration SQL files ordered by version integer."""
        if not self.migrations_dir.exists():
            return []

        migrations = []
        pattern = re.compile(r"^(\d+)_([a-zA-Z0-9_\-]+)\.sql$")
        for file in sorted(self.migrations_dir.iterdir()):
            if not file.is_file():
                continue
            match = pattern.match(file.name)
            if match:
                version = int(match.group(1))
                name = match.group(2)
                content = file.read_text(encoding="utf-8")
                checksum = compute_checksum(content)
                migrations.append(
                    Migration(
                        version=version,
                        name=name,
                        file_path=file,
                        checksum=checksum,
                        sql=content,
                    )
                )

        migrations.sort(key=lambda m: m.version)
        return migrations

    def get_applied_migrations(self, conn: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
        """Retrieves currently applied migrations indexed by version."""
        self.ensure_migration_table(conn)
        cursor = conn.execute("SELECT version, name, applied_at, checksum FROM schema_migrations ORDER BY version ASC;")
        applied = {}
        for row in cursor.fetchall():
            applied[row["version"]] = {
                "version": row["version"],
                "name": row["name"],
                "applied_at": row["applied_at"],
                "checksum": row["checksum"],
            }
        return applied

    def verify_integrity(self, conn: sqlite3.Connection, available_migrations: List[Migration]) -> None:
        """Verifies that applied migrations match their disk files and haven't been mutated."""
        applied = self.get_applied_migrations(conn)
        for m in available_migrations:
            if m.version in applied:
                rec = applied[m.version]
                if rec["checksum"] != m.checksum:
                    raise MigrationIntegrityError(
                        f"Migration {m.version:03d}_{m.name} checksum mismatch! "
                        f"Database has '{rec['checksum']}', disk has '{m.checksum}'."
                    )

    def apply_pending(self) -> List[int]:
        """Applies all unapplied migrations transactionally in sequential order.

        Returns list of applied migration versions.
        """
        conn = self._get_connection()
        applied_versions = []
        try:
            self.ensure_migration_table(conn)
            migrations = self.discover_migrations()
            self.verify_integrity(conn, migrations)
            applied = self.get_applied_migrations(conn)

            for m in migrations:
                if m.version in applied:
                    continue

                # Execute migration inside a managed transaction
                statements = split_sql_statements(m.sql)
                try:
                    conn.execute("BEGIN IMMEDIATE;")
                    for stmt in statements:
                        conn.execute(stmt)

                    now_utc = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?);",
                        (m.version, m.name, now_utc, m.checksum),
                    )
                    conn.commit()
                    applied_versions.append(m.version)
                except Exception as e:
                    conn.rollback()
                    raise MigrationExecutionError(
                        f"Failed executing migration {m.version:03d}_{m.name}: {e}"
                    ) from e

            return applied_versions
        finally:
            conn.close()


def run_all_migrations(db_path: Optional[str] = None) -> List[int]:
    """Convenience entry point to run migrations against the configured or given database."""
    runner = MigrationRunner(db_path or AIRA_DB_PATH)
    return runner.apply_pending()
