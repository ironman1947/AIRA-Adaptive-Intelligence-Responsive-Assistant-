"""Comprehensive verification of AIRA persistent conversation lifecycle across restarts and sessions."""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.memory.database import DatabaseManager
from src.memory.repository import MemoryRepository
from src.config import AIRA_DB_PATH

client = TestClient(app)

def test_full_conversation_persistence_lifecycle(tmp_path):
    # Isolated test database to simulate clean restart
    test_db_file = tmp_path / "persistence_test.db"
    db_mgr = DatabaseManager(str(test_db_file))
    repo = MemoryRepository(db_mgr)

    # 1. Create two distinct conversations
    conv_1 = repo.create_conversation(title="New Conversation")
    conv_2 = repo.create_conversation(title="New Conversation")
    cid_1 = conv_1.id
    cid_2 = conv_2.id
    assert cid_1 != cid_2

    # 2. Add turns to Conversation 1
    # First turn auto-generates title from user prompt
    repo.add_message(cid_1, role="user", content="What is quantum entanglement?")
    repo.add_message(cid_1, role="assistant", content="Quantum entanglement is a phenomenon...", engine="cloud", model="nemotron")

    # Second turn in Conversation 1
    repo.add_message(cid_1, role="user", content="Can it be used for faster-than-light communication?")
    repo.add_message(cid_1, role="assistant", content="No, according to the no-communication theorem...", engine="cloud", model="nemotron")

    # 3. Add turns to Conversation 2
    repo.add_message(cid_2, role="user", content="Can you write a python script to parse logs?")
    repo.add_message(cid_2, role="assistant", content="Here is a python script...", engine="local", model="gemma:2b")

    # Verify Conversation 1 state
    c1_loaded = repo.get_conversation(cid_1)
    assert c1_loaded.title == "Quantum entanglement"
    c1_msgs = repo.get_messages(cid_1)
    assert len(c1_msgs) == 4
    assert c1_msgs[0].content == "What is quantum entanglement?"
    assert c1_msgs[1].content == "Quantum entanglement is a phenomenon..."
    assert c1_msgs[2].content == "Can it be used for faster-than-light communication?"
    assert c1_msgs[3].content == "No, according to the no-communication theorem..."

    # Verify Conversation 2 state
    c2_loaded = repo.get_conversation(cid_2)
    assert c2_loaded.title == "Write a python script to parse logs"
    c2_msgs = repo.get_messages(cid_2)
    assert len(c2_msgs) == 2
    assert c2_msgs[0].content == "Can you write a python script to parse logs?"
    assert c2_msgs[1].model == "gemma:2b"

    # 4. Rename Conversation 1
    repo.update_conversation(cid_1, title="Physics - Quantum Entanglement")
    assert repo.get_conversation(cid_1).title == "Physics - Quantum Entanglement"

    # 5. SIMULATE COMPLETE SERVER RESTART:
    # Completely destroy repo & db instances, reopen the file with a fresh instance
    del repo
    del db_mgr

    fresh_db_mgr = DatabaseManager(str(test_db_file))
    fresh_repo = MemoryRepository(fresh_db_mgr)

    # Verify that all conversations and messages survived the simulated restart
    restarted_convs = fresh_repo.list_conversations()
    assert len(restarted_convs) == 2
    assert any(c.id == cid_1 and c.title == "Physics - Quantum Entanglement" for c in restarted_convs)
    assert any(c.id == cid_2 and c.title == "Write a python script to parse logs" for c in restarted_convs)

    restarted_msgs_1 = fresh_repo.get_messages(cid_1)
    assert len(restarted_msgs_1) == 4
    assert restarted_msgs_1[0].content == "What is quantum entanglement?"
    assert restarted_msgs_1[3].content == "No, according to the no-communication theorem..."

    restarted_msgs_2 = fresh_repo.get_messages(cid_2)
    assert len(restarted_msgs_2) == 2
    assert restarted_msgs_2[0].content == "Can you write a python script to parse logs?"

    # 6. Delete Conversation 2 and verify cascade
    fresh_repo.delete_conversation(cid_2)
    assert fresh_repo.get_conversation(cid_2) is None
    assert len(fresh_repo.get_messages(cid_2)) == 0

    # Conversation 1 remains untouched
    assert fresh_repo.get_conversation(cid_1) is not None
    assert len(fresh_repo.get_messages(cid_1)) == 4


def test_api_chat_flow_session_persistence():
    # Test through FastAPI client
    conv_id = "test_e2e_persistence_conv_999"

    # 1. Ask a deterministic time query through /api/chat
    r1 = client.post("/api/chat", json={"prompt": "What's the system time?", "session_id": conv_id})
    assert r1.status_code == 200
    res1 = r1.json()
    assert "result" in res1
    assert "IST" in res1["result"] or "time" in res1["result"].lower()

    # 2. Ask a follow-up query
    r2 = client.post("/api/chat", json={"prompt": "Who are you?", "session_id": conv_id})
    assert r2.status_code == 200
    res2 = r2.json()
    assert "AIRA" in res2["result"]

    # 3. Retrieve conversation via GET /api/conversations/{conv_id}
    conv_res = client.get(f"/api/conversations/{conv_id}")
    assert conv_res.status_code == 200
    conv_json = conv_res.json()
    assert conv_json["id"] == conv_id
    assert len(conv_json["messages"]) == 4

    # Verify messages in order: user, assistant, user, assistant
    assert conv_json["messages"][0]["role"] == "user"
    assert conv_json["messages"][0]["content"] == "What's the system time?"
    assert conv_json["messages"][1]["role"] == "assistant"
    assert conv_json["messages"][2]["role"] == "user"
    assert conv_json["messages"][2]["content"] == "Who are you?"
    assert conv_json["messages"][3]["role"] == "assistant"

    # Clean up
    client.delete(f"/api/conversations/{conv_id}")
