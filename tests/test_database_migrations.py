"""Tests for AIRA Database Migration Foundation and Schema Evolution."""

import sqlite3
import pytest
from pathlib import Path

from src.memory.database import DatabaseManager
from src.memory.migrations.runner import (
    MigrationRunner,
    MigrationIntegrityError,
    MigrationExecutionError,
    split_sql_statements,
    compute_checksum,
)
from src.tasks.repository import TaskRepository
from src.tasks.models import Task, TaskStatus


def test_split_sql_statements_handles_quotes_and_semicolons():
    sql = """
    -- Comment
    CREATE TABLE foo (id TEXT, val TEXT);
    INSERT INTO foo (id, val) VALUES ('1;2;3', "hello;world");
    SELECT * FROM foo;
    """
    stmts = split_sql_statements(sql)
    assert len(stmts) == 3
    assert stmts[0].startswith("CREATE TABLE foo")
    assert "1;2;3" in stmts[1]


def test_fresh_database_initialization_applies_migrations(tmp_path):
    db_file = str(tmp_path / "fresh_aira.db")
    db_mgr = DatabaseManager(db_file)

    with db_mgr.connection() as conn:
        # Verify schema_migrations exists
        cursor = conn.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version ASC;")
        migrations = cursor.fetchall()
        assert len(migrations) >= 1
        assert migrations[0]["version"] == 1
        assert migrations[0]["name"] == "tasks_and_governance"

        # Verify new tables exist
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert "tasks" in tables
        assert "task_events" in tables
        assert "approval_requests" in tables
        assert "action_events" in tables
        assert "schema_migrations" in tables
        # Verify existing tables still exist
        assert "conversations" in tables
        assert "messages" in tables
        assert "user_profile" in tables


def test_migration_idempotency_repeated_runs_do_not_reapply(tmp_path):
    db_file = str(tmp_path / "repeat_test.db")
    runner = MigrationRunner(db_file)

    first_run = runner.apply_pending()
    assert 1 in first_run

    # Second run should apply nothing
    second_run = runner.apply_pending()
    assert second_run == []


def test_migration_integrity_detects_tampering(tmp_path):
    db_file = str(tmp_path / "tamper_test.db")
    runner = MigrationRunner(db_file)
    runner.apply_pending()

    # Tamper with the recorded checksum
    conn = sqlite3.connect(db_file)
    conn.execute("UPDATE schema_migrations SET checksum = 'tampered_fake_checksum' WHERE version = 1;")
    conn.commit()
    conn.close()

    # Next run must raise MigrationIntegrityError
    with pytest.raises(MigrationIntegrityError):
        runner.apply_pending()


def test_migration_transaction_rollback_on_failure(tmp_path):
    db_file = str(tmp_path / "rollback_test.db")

    # Custom migration dir with a failing migration
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    # Valid migration 001
    (mig_dir / "001_good.sql").write_text("CREATE TABLE good_table (id TEXT PRIMARY KEY);")
    # Invalid migration 002 with syntax error
    (mig_dir / "002_bad.sql").write_text("CREATE TABLE bad_table (id TEXT PRIMARY KEY); SYNTAX ERROR HERE;")

    runner = MigrationRunner(db_file, migrations_dir=mig_dir)
    with pytest.raises(MigrationExecutionError):
        runner.apply_pending()

    # Verify migration 001 succeeded but migration 002 was rolled back
    conn = sqlite3.connect(db_file)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    assert "good_table" in tables
    assert "bad_table" not in tables

    # schema_migrations must only have version 1
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations;").fetchall()]
    assert versions == [1]
    conn.close()


def test_foreign_key_constraints_enforced(tmp_path):
    db_file = str(tmp_path / "fk_test.db")
    db_mgr = DatabaseManager(db_file)
    repo = TaskRepository(db_mgr)

    # Creating a task with non-existent conversation_id should fail if foreign_keys is on
    task = Task(
        id="task_invalid_fk",
        title="Test Invalid FK",
        conversation_id="non_existent_conversation_999",
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_task(task)


def test_existing_records_preserved_on_migration(tmp_path):
    db_file = str(tmp_path / "preserve_test.db")

    # Initialize older schema manually with AIRA 1.0 conversations table
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default_user',
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT DEFAULT '{}'
        );
        """
    )
    conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c1', 'My Prior Chat', '2026-01-01', '2026-01-01');")
    conn.commit()
    conn.close()

    # Run DatabaseManager / MigrationRunner
    db_mgr = DatabaseManager(db_file)

    # Verify existing conversation preserved
    with db_mgr.connection() as c:
        row = c.execute("SELECT title FROM conversations WHERE id = 'c1';").fetchone()
        assert row is not None
        assert row["title"] == "My Prior Chat"

        # Verify new tables were also added
        new_tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert "tasks" in new_tables
        assert "approval_requests" in new_tables
