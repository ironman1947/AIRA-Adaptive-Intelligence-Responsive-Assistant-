"""Tests for frontend message rendering null-safety across all metadata permutations."""

import pytest
from frontend import resolve_engine_and_model_badge

def test_message_rendering_model_is_none():
    msg = {"role": "assistant", "content": "Test response", "model": None, "engine": None}
    badge = resolve_engine_and_model_badge(msg)
    assert badge == "AIRA Assistant"


def test_message_rendering_model_key_missing():
    msg = {"role": "assistant", "content": "Legacy response without model key"}
    badge = resolve_engine_and_model_badge(msg)
    assert badge == "AIRA Assistant"


def test_message_rendering_model_is_gemma_local():
    # Test case 1: model is gemma:2b, engine is None
    msg1 = {"role": "assistant", "content": "Local response", "model": "gemma:2b", "engine": None}
    badge1 = resolve_engine_and_model_badge(msg1)
    assert badge1 == "Local Gemma 2B"

    # Test case 2: engine is local, model is None
    msg2 = {"role": "assistant", "content": "Local response", "model": None, "engine": "local"}
    badge2 = resolve_engine_and_model_badge(msg2)
    assert badge2 == "Local Gemma 2B"


def test_message_rendering_model_is_cloud():
    # Test case 1: cloud model name present
    msg1 = {
        "role": "assistant",
        "content": "Cloud response",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "engine": None,
    }
    badge1 = resolve_engine_and_model_badge(msg1)
    assert badge1 == "Cloud Nemotron"

    # Test case 2: engine is cloud, model is None
    msg2 = {"role": "assistant", "content": "Cloud response", "model": None, "engine": "cloud"}
    badge2 = resolve_engine_and_model_badge(msg2)
    assert badge2 == "Cloud Nemotron"


def test_message_rendering_engine_is_none():
    msg = {"role": "assistant", "content": "Response", "engine": None, "model": None}
    badge = resolve_engine_and_model_badge(msg)
    assert badge == "AIRA Assistant"


def test_message_rendering_with_tool_assisted():
    msg = {
        "role": "assistant",
        "content": "Tool response",
        "engine": "local",
        "model": "gemma:2b",
        "tools_triggered": True,
    }
    badge = resolve_engine_and_model_badge(msg)
    assert "Tool Assisted" in badge
    assert "Local Gemma 2B" in badge
