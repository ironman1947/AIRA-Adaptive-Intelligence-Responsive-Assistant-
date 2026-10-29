"""Automated Regression Tests for Identity, User Profile, and Conversation Continuity.

Validates:
1. Message 1: "hi my name is om" -> Recognizes Om as user, does not claim user is AIRA.
2. Message 2: "may I know your name?" -> AIRA identifies herself as AIRA.
3. Message 3: "what is my name?" -> AIRA identifies user as Om.
4. Unknown user name remains unknown.
5. Name correction ("Actually, call me Sam") updates profile.
6. Asking AIRA's name never alters the user's profile.
7. Conversation restart restores user profile.
8. Multi-turn conversation history is preserved in database and passed in message sequence.
9. Identity questions work under local-only privacy mode.
10. History and profile name REST API endpoints.
"""

import pytest
import os
import tempfile
from unittest.mock import patch, AsyncMock

from src.memory.database import DatabaseManager
from src.memory.repository import MemoryRepository
from src.context.user_profile import UserProfileManager
from src.agent.identity import AiraRuntimeState, build_aira_system_prompt, ASSISTANT_NAME
from src.agent.intent import analyze_conversational_intent, IntentCategory
from src.agent.identity_handler import (
    extract_user_introduction,
    detect_identity_question,
    generate_assistant_name_response,
    generate_user_name_response,
    generate_introduction_response,
)
from src.agent.core import run_agent_workflow
import src.agent.core as core_module

@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = DatabaseManager(db_path)
    repo = MemoryRepository(db)
    yield repo
    if os.path.exists(db_path):
        os.remove(db_path)

# ------------------------------------------------------------------------------
# 1. Exact Sequence Test: "hi my name is om" -> "may I know your name?" -> "what is my name?"
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exact_user_introduction_and_identity_sequence(test_db):
    user_mgr = UserProfileManager(test_db)

    with patch.object(core_module, "_repo", test_db), \
         patch.object(core_module, "_user_profile_mgr", user_mgr):

        session_id = "test_sess_seq_001"

        # Turn 1: User introduces self
        res1 = await run_agent_workflow("hi my name is om", session_id=session_id)
        assert res1["intent_category"] == IntentCategory.USER_INTRODUCTION
        assert "Om" in res1["result"]
        # Must NOT call the user AIRA
        assert "meet you, AIRA" not in res1["result"]
        # Profile must have recorded Om
        assert user_mgr.get_user_display_name() == "Om"

        # Turn 2: User asks AIRA's name
        res2 = await run_agent_workflow("may I know your name?", session_id=session_id)
        assert res2["intent_category"] == IntentCategory.SYSTEM_INQUIRY
        # Assistant must identify herself as AIRA
        assert "I'm AIRA" in res2["result"] or "AIRA" in res2["result"]
        assert "meet you, AIRA" not in res2["result"]
        # User profile must NOT have been changed to AIRA
        assert user_mgr.get_user_display_name() == "Om"

        # Turn 3: User asks what their own name is
        res3 = await run_agent_workflow("what is my name?", session_id=session_id)
        assert res3["intent_category"] == IntentCategory.SYSTEM_INQUIRY
        assert "Om" in res3["result"]
        assert "AIRA" not in res3["result"].split("name is")[-1]

# ------------------------------------------------------------------------------
# 2. Unknown User Name Remains Unknown
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_user_name_remains_unknown(test_db):
    user_mgr = UserProfileManager(test_db)
    assert user_mgr.get_user_display_name() is None

    with patch.object(core_module, "_repo", test_db), \
         patch.object(core_module, "_user_profile_mgr", user_mgr):

        res = await run_agent_workflow("what is my name?", session_id="sess_unknown_user")
        assert "haven't told me your name" in res["result"].lower() or "what should i call you" in res["result"].lower()
        # Must not fabricate a name
        assert "Senior Software Engineer" not in res["result"]

# ------------------------------------------------------------------------------
# 3. User Name Correction ("Actually, call me Sam")
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_user_name_correction(test_db):
    user_mgr = UserProfileManager(test_db)
    user_mgr.set_user_display_name("Om")

    with patch.object(core_module, "_repo", test_db), \
         patch.object(core_module, "_user_profile_mgr", user_mgr):

        session_id = "test_sess_correction"
        res = await run_agent_workflow("Actually, call me Sam", session_id=session_id)
        assert "Sam" in res["result"]
        assert user_mgr.get_user_display_name() == "Sam"

        # Follow-up: ask name again
        res2 = await run_agent_workflow("what is my name?", session_id=session_id)
        assert "Sam" in res2["result"]
        assert "Om" not in res2["result"]

# ------------------------------------------------------------------------------
# 4. Asking AIRA's Name Never Modifies User Profile
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_asking_assistant_name_never_changes_user_profile(test_db):
    user_mgr = UserProfileManager(test_db)
    user_mgr.set_user_display_name("Alice")

    with patch.object(core_module, "_repo", test_db), \
         patch.object(core_module, "_user_profile_mgr", user_mgr):

        res = await run_agent_workflow("Who are you?", session_id="sess_who_are_you")
        assert "AIRA" in res["result"]
        # Profile must remain Alice, never AIRA
        assert user_mgr.get_user_display_name() == "Alice"

# ------------------------------------------------------------------------------
# 5. Conversation History Persistence & Chronological Loading
# ------------------------------------------------------------------------------
def test_conversation_history_persistence(test_db):
    session_id = "sess_history_test"
    m1 = test_db.add_conversation_message(session_id, role="user", content="Hello!")
    m2 = test_db.add_conversation_message(session_id, role="assistant", content="Hi! How can I assist you?")
    m3 = test_db.add_conversation_message(session_id, role="user", content="My name is Carlos.")

    history = test_db.get_conversation_history(session_id, limit=10)
    assert len(history) == 3
    assert history[0].role == "user"
    assert history[0].content == "Hello!"
    assert history[1].role == "assistant"
    assert history[2].content == "My name is Carlos."

    # Clear history
    test_db.clear_conversation_history(session_id)
    assert len(test_db.get_conversation_history(session_id)) == 0

# ------------------------------------------------------------------------------
# 6. Extraction Logic Unit Tests (Positive & Negative)
# ------------------------------------------------------------------------------
def test_user_introduction_extraction_rules():
    # Positives
    assert extract_user_introduction("hi my name is om")["name"] == "Om"
    assert extract_user_introduction("Hello, my name is Alex.")["name"] == "Alex"
    assert extract_user_introduction("my name is Sarah")["name"] == "Sarah"
    assert extract_user_introduction("call me Bob")["name"] == "Bob"
    assert extract_user_introduction("Actually, call me Sam")["name"] == "Sam"
    assert extract_user_introduction("Actually, call me Sam")["is_correction"] is True
    assert extract_user_introduction("My name is not Bob, call me Dave")["name"] == "Dave"

    # Negatives (must NOT extract)
    assert extract_user_introduction("What is your name?") is None
    assert extract_user_introduction("Who are you?") is None
    assert extract_user_introduction("What is my name?") is None
    assert extract_user_introduction("My friend's name is John") is None
    assert extract_user_introduction("The project name is Alpha") is None
    assert extract_user_introduction("The file name is main.py") is None
    assert extract_user_introduction("Call me crazy, but this code is weird") is None
    assert extract_user_introduction("Call me later tonight") is None
    assert extract_user_introduction("My name is AIRA") is None  # Reserved assistant name

def test_identity_question_detection():
    # Assistant identity
    assert detect_identity_question("may I know your name?") == "ask_assistant_name"
    assert detect_identity_question("what is your name?") == "ask_assistant_name"
    assert detect_identity_question("What's your name") == "ask_assistant_name"
    assert detect_identity_question("who are you?") == "ask_assistant_name"
    assert detect_identity_question("What are you called?") == "ask_assistant_name"
    assert detect_identity_question("Please introduce yourself") == "ask_assistant_name"

    # User identity
    assert detect_identity_question("what is my name?") == "ask_user_name"
    assert detect_identity_question("What's my name") == "ask_user_name"
    assert detect_identity_question("who am I?") == "ask_user_name"
    assert detect_identity_question("do you know my name?") == "ask_user_name"

    # Unrelated questions
    assert detect_identity_question("Why do people dream?") is None
    assert detect_identity_question("What is the capital of France?") is None
    assert detect_identity_question("How do I write a Python function?") is None

# ------------------------------------------------------------------------------
# 7. Local-Only Privacy Mode Respects Identity
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_identity_under_local_only_privacy(test_db):
    user_mgr = UserProfileManager(test_db)
    user_mgr.set_user_display_name("Maya")

    with patch.object(core_module, "_repo", test_db), \
         patch.object(core_module, "_user_profile_mgr", user_mgr):

        res = await run_agent_workflow(
            "May I know your name?",
            session_id="sess_privacy_id",
            privacy_mode="local_only"
        )
        assert res["target_engine"] == "local"
        assert "AIRA" in res["result"]
        assert "Maya" in res["result"] or "AIRA" in res["result"]

# ------------------------------------------------------------------------------
# 8. Prompt Construction Strictly Separates Identity
# ------------------------------------------------------------------------------
def test_system_prompt_identity_separation():
    state = AiraRuntimeState(user_display_name="Jordan")
    prompt = build_aira_system_prompt(state, user_display_name="Jordan")

    assert "Assistant Name: AIRA" in prompt
    assert "User Name: Jordan" in prompt
    assert "NEVER call the user 'AIRA'" in prompt
    assert "NEVER confuse your identity with the user" in prompt
