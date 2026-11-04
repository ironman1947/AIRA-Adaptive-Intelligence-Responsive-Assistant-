"""Tests for AIRA Persistent Conversation Management and API Endpoints."""

import pytest
from fastapi.testclient import TestClient
from src.main import app, repo
from src.memory.models import Conversation, Message
from src.memory.repository import generate_conversation_title

client = TestClient(app)

def test_generate_conversation_title():
    assert generate_conversation_title("Hello AIRA, what is quantum computing?") == "Quantum computing"
    assert generate_conversation_title("Can you write a python script to parse logs?") == "Write a python script to parse logs"
    assert generate_conversation_title("What is the time right now?") == "Time right now"
    assert generate_conversation_title("   ") == "New Conversation"


def test_create_and_list_conversations():
    # 1. Create a conversation
    resp = client.post("/api/conversations", json={"title": "Test Chat Alpha"})
    assert resp.status_code == 200
    data = resp.json()
    conv_id = data["id"]
    assert data["title"] == "Test Chat Alpha"
    assert "created_at" in data
    assert "updated_at" in data

    # 2. List conversations
    list_resp = client.get("/api/conversations")
    assert list_resp.status_code == 200
    conv_list = list_resp.json()
    assert any(c["id"] == conv_id for c in conv_list)

    # Clean up
    client.delete(f"/api/conversations/{conv_id}")


def test_get_conversation_and_messages():
    # Create conversation
    create_resp = client.post("/api/conversations", json={"title": "Message Test"})
    conv_id = create_resp.json()["id"]

    # Add user message
    msg_resp = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "Explain binary search", "engine": "local"},
    )
    assert msg_resp.status_code == 200
    msg_data = msg_resp.json()
    assert msg_data["role"] == "user"
    assert msg_data["content"] == "Explain binary search"

    # Add assistant message
    asst_resp = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={
            "role": "assistant",
            "content": "Binary search works by...",
            "engine": "local",
            "model": "gemma:2b",
        },
    )
    assert asst_resp.status_code == 200

    # Fetch conversation with messages
    get_resp = client.get(f"/api/conversations/{conv_id}")
    assert get_resp.status_code == 200
    details = get_resp.json()
    assert details["id"] == conv_id
    assert len(details["messages"]) == 2
    assert details["messages"][0]["role"] == "user"
    assert details["messages"][1]["role"] == "assistant"
    assert details["messages"][1]["model"] == "gemma:2b"

    # Clean up
    client.delete(f"/api/conversations/{conv_id}")


def test_rename_and_delete_conversation():
    create_resp = client.post("/api/conversations", json={"title": "Old Name"})
    conv_id = create_resp.json()["id"]

    # Rename
    patch_resp = client.patch(
        f"/api/conversations/{conv_id}",
        json={"title": "Updated Brand New Title"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Updated Brand New Title"

    # Verify update
    get_resp = client.get(f"/api/conversations/{conv_id}")
    assert get_resp.json()["title"] == "Updated Brand New Title"

    # Delete
    del_resp = client.delete(f"/api/conversations/{conv_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Confirm 404 after deletion
    not_found = client.get(f"/api/conversations/{conv_id}")
    assert not_found.status_code == 404


def test_search_conversations():
    c1 = client.post("/api/conversations", json={"title": "Machine Learning Deep Dive"}).json()["id"]
    c2 = client.post("/api/conversations", json={"title": "Cooking Recipes for Pasta"}).json()["id"]

    search_resp = client.get("/api/conversations?search=Machine")
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert any(c["id"] == c1 for c in results)
    assert not any(c["id"] == c2 for c in results)

    # Clean up
    client.delete(f"/api/conversations/{c1}")
    client.delete(f"/api/conversations/{c2}")


def test_chat_endpoint_persists_to_conversation():
    conv_id = "test_chat_persists_session_123"

    # Send message to /api/chat
    chat_resp = client.post(
        "/api/chat",
        json={"prompt": "What is the time right now?", "session_id": conv_id},
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert "result" in chat_data

    # Verify conversation was automatically registered and messages were saved
    conv_resp = client.get(f"/api/conversations/{conv_id}")
    assert conv_resp.status_code == 200
    conv_data = conv_resp.json()
    assert conv_data["id"] == conv_id
    assert len(conv_data["messages"]) >= 2
    assert conv_data["messages"][0]["role"] == "user"
    assert conv_data["messages"][1]["role"] == "assistant"

    # Clean up
    client.delete(f"/api/conversations/{conv_id}")

