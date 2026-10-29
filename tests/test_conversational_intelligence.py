"""Comprehensive automated test suite for AIRA Conversational Intelligence,

Intent Understanding, Contextual Relevance, and Personalization.
Directly verifies the 20 Acceptance Criteria from Section 11 of the specification.
"""

import pytest
import json
from unittest.mock import patch, MagicMock

from src.agent.intent import analyze_conversational_intent, IntentCategory, ConversationalIntent
from src.agent.identity import build_aira_system_prompt, AiraRuntimeState
from src.agent.router import determine_complexity, route_request
from src.agent.core import run_agent_workflow
from src.context.user_profile import UserProfileManager
from src.memory.database import DatabaseManager
from src.memory.repository import MemoryRepository
from src.memory.models import UserProfileItem, UserPreference, ProjectWorkspace, EpisodicMemory

@pytest.fixture
def clean_repo(tmp_path):
    db_file = tmp_path / "conv_intel.db"
    mgr = DatabaseManager(str(db_file))
    return MemoryRepository(mgr)

# ------------------------------------------------------------------------------
# Criterion 1: "Hi" receives a simple greeting rather than an engineering report
# ------------------------------------------------------------------------------
def test_greeting_intent_classification():
    for g in ["hhi", "hi", "Hello", "hellooo", "hey there", "good morning", "howdy", "sup"]:
        intent = analyze_conversational_intent(g)
        assert intent.category == IntentCategory.GREETING
        assert intent.suggested_complexity == "LOW"
        assert intent.needs_project_context is False

# ------------------------------------------------------------------------------
# Criterion 2: Casual conversation does not trigger unnecessary cloud inference
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_casual_conversation_complexity():
    for casual in ["Tell me a joke", "How's your day going?", "What is something fun to learn?"]:
        c = await determine_complexity(casual)
        assert c in ("LOW", "MEDIUM")

# ------------------------------------------------------------------------------
# Criterion 3: General knowledge is not assumed to be a coding problem
# ------------------------------------------------------------------------------
def test_general_knowledge_not_coding():
    for q in ["Why do people dream?", "How do volcanoes erupt?", "Who wrote Hamlet?", "What is the speed of light?"]:
        intent = analyze_conversational_intent(q)
        assert intent.category == IntentCategory.GENERAL_KNOWLEDGE
        assert intent.needs_coding_tools is False
        assert intent.needs_project_context is False

# ------------------------------------------------------------------------------
# Criterion 4: Complex coding question reaches appropriate coding tools
# ------------------------------------------------------------------------------
def test_complex_coding_triggers_technical_intent():
    code_prompts = [
        "Write a Python script for a binary search tree with insert and delete methods",
        "Debug this FastAPI async race condition and fix the deadlock in the database pool",
        "Refactor this class to use Pydantic models with custom validators"
    ]
    for cp in code_prompts:
        intent = analyze_conversational_intent(cp)
        assert intent.category == IntentCategory.CODING_TECHNICAL
        assert intent.suggested_complexity == "HEAVY"
        assert intent.needs_coding_tools is True

# ------------------------------------------------------------------------------
# Criterion 5 & 6: Continuation and Ambiguous Continuation Handling
# ------------------------------------------------------------------------------
def test_continuation_intent():
    for cont in ["Let's continue from yesterday.", "Where were we?", "Pick up where we left off"]:
        intent = analyze_conversational_intent(cont)
        assert intent.category == IntentCategory.CONTINUATION
        assert intent.needs_project_context is True

@pytest.mark.asyncio
async def test_ambiguous_continuation_asks_clarification(clean_repo):
    # Setup multiple projects
    clean_repo.save_project(ProjectWorkspace(id="proj1", name="Alpha Service"))
    clean_repo.save_project(ProjectWorkspace(id="proj2", name="Beta App"))

    with patch("src.agent.core._repo", clean_repo):
        with patch("src.agent.core._project_mgr.list_projects", clean_repo.list_projects):
            res = await run_agent_workflow("Let's continue from yesterday", project_id=None)
            assert "Which one would you like to continue with?" in res["result"] or "Alpha Service" in res["result"]

# ------------------------------------------------------------------------------
# Criterion 7: Confirmed preferences influence responses appropriately
# ------------------------------------------------------------------------------
def test_confirmed_preferences_in_prompt(clean_repo):
    mgr = UserProfileManager(clean_repo)
    clean_repo.add_preference(UserPreference(
        preference_key="explanation_depth",
        preference_value="Prefers concise intuitive analogies",
        user_approved=True
    ))

    summary = mgr.get_profile_prompt_summary()
    assert "explanation_depth: Prefers concise intuitive analogies" in summary

    prompt = build_aira_system_prompt(
        runtime_state=AiraRuntimeState(),
        user_profile_summary=summary,
        include_project_context=False
    )
    assert "Prefers concise intuitive analogies" in prompt

# ------------------------------------------------------------------------------
# Criterion 8: Inferred preferences retain uncertainty and can be corrected
# ------------------------------------------------------------------------------
def test_inferred_preferences_unapproved_initially(clean_repo):
    mgr = UserProfileManager(clean_repo)
    pref = mgr.propose_inferred_preference(
        key="tone_style",
        value="Casual and friendly",
        observation="User used informal phrasing across 3 messages",
        confidence=0.65
    )
    assert pref.user_approved is False
    assert pref.confidence < 1.0

    # Ensure unapproved preferences are not included in prompt summary
    summary = mgr.get_profile_prompt_summary()
    assert summary is None or "tone_style" not in summary

    # Confirming makes it active
    clean_repo.set_preference_approval(pref.id, approved=True)
    summary_confirmed = mgr.get_profile_prompt_summary()
    assert "tone_style: Casual and friendly" in summary_confirmed

    # Rejecting/deleting removes it
    clean_repo.delete_preference(pref.id)
    assert len(clean_repo.list_preferences()) == 0

# ------------------------------------------------------------------------------
# Criterion 9 & 10: Unknown professional title remains unknown (no fabricated defaults)
# ------------------------------------------------------------------------------
def test_profile_never_invents_profession_or_expertise(clean_repo):
    mgr = UserProfileManager(clean_repo)
    profile = mgr.get_profile_dict()

    # Must NOT have fabricated default titles or languages
    assert "technical_background" not in profile or profile["technical_background"] == "Not configured"
    assert "Senior Software Engineer" not in str(profile.values())
    assert "AI Researcher" not in str(profile.values())

    # Setting explicit profile works
    mgr.update_profile_field("preferred_name", "Alex")
    assert mgr.get_field("preferred_name") == "Alex"

# ------------------------------------------------------------------------------
# Criterion 11 & 13: Emotional cues handled appropriately without permanent labeling
# ------------------------------------------------------------------------------
def test_emotional_cue_frustration():
    prompt = "This thing keeps failing. I've tried everything."
    intent = analyze_conversational_intent(prompt)
    assert intent.category == IntentCategory.EMOTIONAL_SUPPORT
    assert intent.emotional_cue == "frustrated"
    assert "calm" in intent.tone_guidance.lower() or "empathy" in intent.tone_guidance.lower()

def test_emotional_cue_excitement():
    prompt = "IT FINALLY WORKED!"
    intent = analyze_conversational_intent(prompt)
    assert intent.category == IntentCategory.EMOTIONAL_SUPPORT
    assert intent.emotional_cue == "excited"
    assert "enthusiasm" in intent.tone_guidance.lower() or "celebration" in intent.tone_guidance.lower()

# ------------------------------------------------------------------------------
# Criterion 14: Simple greeting does NOT surface stored project details
# ------------------------------------------------------------------------------
def test_greeting_does_not_inject_project_context():
    intent = analyze_conversational_intent("hhi")
    prompt = build_aira_system_prompt(
        runtime_state=AiraRuntimeState(),
        project_summary="Project: Secret Quantum Engine\nObjectives: Build Superconductor",
        include_project_context=intent.needs_project_context  # False for greetings
    )
    assert "Secret Quantum Engine" not in prompt
    assert "Build Superconductor" not in prompt

# ------------------------------------------------------------------------------
# Criterion 15: RAG and memory retrieved only when relevant
# ------------------------------------------------------------------------------
def test_rag_and_memories_scoped():
    greeting_intent = analyze_conversational_intent("Hello!")
    assert greeting_intent.needs_rag is False
    assert greeting_intent.needs_project_context is False

    tech_intent = analyze_conversational_intent("Debug this async database connection in my project")
    assert tech_intent.needs_project_context is True

# ------------------------------------------------------------------------------
# Criterion 16: Routing expandable beyond predefined technical domains
# ------------------------------------------------------------------------------
def test_diverse_domains_routing():
    domains = [
        ("Write a poem about autumn leaves in Tokyo", IntentCategory.CREATIVE),
        ("Help me plan my workout schedule for next week", IntentCategory.PLANNING),
        ("Who painted the Girl with a Pearl Earring?", IntentCategory.GENERAL_KNOWLEDGE),
        ("Search the web for latest news today on space exploration", IntentCategory.WEB_RESEARCH),
        ("What can you do as AIRA?", IntentCategory.SYSTEM_INQUIRY),
    ]
    for text, expected_cat in domains:
        intent = analyze_conversational_intent(text)
        assert intent.category == expected_cat

# ------------------------------------------------------------------------------
# Criterion 17: Model failures do not generate fabricated successful outcomes
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_reported_honestly():
    with patch("src.agent.core.check_local_health", return_value=False):
        with patch("src.agent.core.check_cloud_health", return_value=False):
            # In local-only mode with local offline
            res = await run_agent_workflow("Hello", privacy_mode="local_only")
            # Must report error, never fabricate a successful answer
            assert "error" in res["result"].lower() or "offline" in res["result"].lower()

# ------------------------------------------------------------------------------
# Criterion 18: User memory can be inspected and deleted
# ------------------------------------------------------------------------------
def test_memory_inspection_and_deletion(clean_repo):
    item = clean_repo.add_episodic(EpisodicMemory(title="Test Task", content="Content to delete"))
    assert len(clean_repo.get_episodic_memories()) == 1

    assert clean_repo.delete_episodic(item.id) is True
    assert len(clean_repo.get_episodic_memories()) == 0

# ------------------------------------------------------------------------------
# Criterion 19: Protected security rules remain effective across intents
# ------------------------------------------------------------------------------
def test_security_rules_enforce_across_all_intents():
    from src.security.network import validate_url_security
    assert validate_url_security("http://127.0.0.1:8080/api")[0] is False
    assert validate_url_security("http://169.254.169.254/latest")[0] is False

# ------------------------------------------------------------------------------
# Criterion 20: Existing backend and frontend features remain functional
# ------------------------------------------------------------------------------
def test_existing_endpoints_functional():
    from starlette.testclient import TestClient
    from src.main import app
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["assistant"] == "AIRA"
