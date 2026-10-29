"""Tests for AIRA Persistent Memory System, Personalization, and Repository Abstractions."""

import pytest
from src.memory.database import DatabaseManager
from src.memory.repository import MemoryRepository
from src.memory.models import (
    UserProfileItem,
    UserPreference,
    ProjectWorkspace,
    EpisodicMemory,
    SemanticMemory,
    ProceduralMemory,
    SessionSummary,
)

@pytest.fixture
def repo(tmp_path):
    db_file = tmp_path / "test_memory.db"
    mgr = DatabaseManager(str(db_file))
    return MemoryRepository(mgr)

def test_user_profile_crud(repo):
    item = UserProfileItem(key="theme", value="dark", source="user_setting")
    repo.set_profile_item(item)

    profile = repo.get_profile()
    assert "theme" in profile
    assert profile["theme"].value == "dark"

    # Update item
    item.value = "system"
    repo.set_profile_item(item)
    assert repo.get_profile()["theme"].value == "system"

    # Delete
    assert repo.delete_profile_item("theme") is True
    assert "theme" not in repo.get_profile()

def test_evidence_based_preferences(repo):
    pref = UserPreference(
        preference_key="coding_style",
        preference_value="Functional and type-hinted",
        supporting_observations="Observed user repeatedly asking for dataclasses and type hints",
        confidence=0.85,
        user_approved=False,
    )
    saved = repo.add_preference(pref)
    assert saved.id is not None

    # Unapproved initially
    approved_list = repo.list_preferences(approved_only=True)
    assert len(approved_list) == 0

    # User approves
    assert repo.set_preference_approval(saved.id, approved=True) is True
    approved_list = repo.list_preferences(approved_only=True)
    assert len(approved_list) == 1
    assert approved_list[0].preference_value == "Functional and type-hinted"

    # Delete preference
    assert repo.delete_preference(saved.id) is True
    assert len(repo.list_preferences()) == 0

def test_project_workspace_isolation(repo):
    p1 = ProjectWorkspace(
        id="proj-alpha",
        name="Project Alpha",
        tech_stack=["Python", "FastAPI"],
        current_objectives=["Build API"]
    )
    p2 = ProjectWorkspace(
        id="proj-beta",
        name="Project Beta",
        tech_stack=["TypeScript", "React"],
        current_objectives=["Build Frontend"]
    )
    repo.save_project(p1)
    repo.save_project(p2)

    all_projs = repo.list_projects()
    assert len(all_projs) == 2

    fetched_alpha = repo.get_project("proj-alpha")
    assert fetched_alpha.name == "Project Alpha"
    assert "FastAPI" in fetched_alpha.tech_stack

def test_episodic_and_semantic_memories(repo):
    # Episodic
    ep = EpisodicMemory(
        title="Debugged SQLite Deadlock",
        content="Added WAL mode and short timeouts",
        event_type="debugging",
        tags=["sqlite", "perf"]
    )
    saved_ep = repo.add_episodic(ep)
    assert saved_ep.id is not None
    assert len(repo.get_episodic_memories()) == 1

    # Semantic
    sem = SemanticMemory(
        subject="AIRA",
        predicate="is_a",
        object_value="Personal AI Companion",
        content="AIRA is designed as a persistent companion and coworker.",
        verification_status="verified"
    )
    saved_sem = repo.add_semantic(sem)
    assert saved_sem.id is not None
    assert len(repo.get_semantic_memories()) == 1

def test_procedural_memory_and_learning(repo):
    proc = ProceduralMemory(
        title="Fix Async Port Conflict",
        applicability="Port already in use error",
        steps=["Identify PID using lsof", "Kill conflicting process", "Restart server"],
        validation_status="draft"
    )
    saved_proc = repo.add_procedural(proc)
    assert saved_proc.validation_status == "draft"

    # Record procedure outcomes
    repo.record_procedure_result(saved_proc.id, success=True)
    repo.record_procedure_result(saved_proc.id, success=True)
    updated = repo.get_procedural_memories()[0]
    assert updated.success_count == 2

def test_persistence_across_app_restart(tmp_path):
    db_file = tmp_path / "restart_test.db"
    mgr1 = DatabaseManager(str(db_file))
    repo1 = MemoryRepository(mgr1)

    repo1.set_profile_item(UserProfileItem(key="username", value="Om"))
    repo1.add_episodic(EpisodicMemory(title="Session 1", content="Init"))

    # Simulate application restart with a fresh repository instance pointing to the same file
    mgr2 = DatabaseManager(str(db_file))
    repo2 = MemoryRepository(mgr2)

    profile = repo2.get_profile()
    assert "username" in profile
    assert profile["username"].value == "Om"
    assert len(repo2.get_episodic_memories()) == 1

def test_export_and_category_clearing(repo):
    repo.set_profile_item(UserProfileItem(key="test", value="123"))
    repo.add_episodic(EpisodicMemory(title="E1", content="C1"))

    exported = repo.export_all_memories()
    assert "user_profile" in exported
    assert "episodic_memory" in exported
    assert len(exported["episodic_memory"]) == 1

    assert repo.clear_memory_category("episodic") is True
    assert len(repo.get_episodic_memories()) == 0
    # Profile should still be intact
    assert "test" in repo.get_profile()
