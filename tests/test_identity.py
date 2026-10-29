"""Tests for AIRA Official Identity, Runtime State, and System Prompt."""

import pytest
from src.agent.identity import (
    ASSISTANT_NAME,
    FULL_TITLE,
    VERSION,
    AiraRuntimeState,
    build_aira_system_prompt,
)

def test_aira_identity_constants():
    assert ASSISTANT_NAME == "AIRA"
    assert "Adaptive Intelligence" in FULL_TITLE
    assert "Responsive Assistant" in FULL_TITLE
    assert VERSION == "1.0.0"

def test_runtime_state_defaults_and_dict():
    state = AiraRuntimeState()
    assert state.name == "AIRA"
    assert state.active_local_model == "gemma:2b"
    assert state.active_cloud_model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert state.privacy_mode == "standard"
    assert len(state.enabled_tools) >= 5

    d = state.to_dict()
    assert isinstance(d, dict)
    assert d["name"] == "AIRA"
    assert "current_time" in d
    assert d["local_model_available"] is True

def test_build_aira_system_prompt():
    state = AiraRuntimeState(active_project_id="test-proj")
    prompt = build_aira_system_prompt(
        runtime_state=state,
        user_profile_summary="Senior Engineer in Python",
        project_summary="Project: AIRA Core Engine",
        session_summary="Completed: Phase 1 Audit",
        relevant_memories=["Prefers concise diffs", "Testing with pytest"]
    )

    assert "AIRA" in prompt
    assert "Adaptive Intelligence & Responsive Assistant" in prompt
    assert "Senior Engineer in Python" in prompt
    assert "Project: AIRA Core Engine" in prompt
    assert "Completed: Phase 1 Audit" in prompt
    assert "Prefers concise diffs" in prompt
    assert "Guardrails:" in prompt
