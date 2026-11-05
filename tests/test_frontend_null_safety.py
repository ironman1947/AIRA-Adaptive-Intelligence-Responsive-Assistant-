"""Tests for UI message rendering null-safety across all metadata permutations."""

import pytest
from src.ui.formatting import resolve_engine_and_model_badge

try:
    import streamlit
    from frontend import resolve_engine_and_model_badge as frontend_resolve_badge
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False
    frontend_resolve_badge = None


def test_message_rendering_model_is_none():
    msg = {"role": "assistant", "content": "Test response", "model": None, "engine": None}
    assert resolve_engine_and_model_badge(msg) == "AIRA Assistant"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg) == "AIRA Assistant"


def test_message_rendering_model_key_missing():
    msg = {"role": "assistant", "content": "Legacy response without model key"}
    assert resolve_engine_and_model_badge(msg) == "AIRA Assistant"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg) == "AIRA Assistant"


def test_message_rendering_model_is_gemma_local():
    # Test case 1: model is gemma:2b, engine is None
    msg1 = {"role": "assistant", "content": "Local response", "model": "gemma:2b", "engine": None}
    assert resolve_engine_and_model_badge(msg1) == "Local Gemma 2B"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg1) == "Local Gemma 2B"

    # Test case 2: engine is local, model is None
    msg2 = {"role": "assistant", "content": "Local response", "model": None, "engine": "local"}
    assert resolve_engine_and_model_badge(msg2) == "Local Gemma 2B"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg2) == "Local Gemma 2B"


def test_message_rendering_model_is_cloud():
    # Test case 1: cloud model name present
    msg1 = {
        "role": "assistant",
        "content": "Cloud response",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "engine": None,
    }
    assert resolve_engine_and_model_badge(msg1) == "Cloud Nemotron"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg1) == "Cloud Nemotron"

    # Test case 2: engine is cloud, model is None
    msg2 = {"role": "assistant", "content": "Cloud response", "model": None, "engine": "cloud"}
    assert resolve_engine_and_model_badge(msg2) == "Cloud Nemotron"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg2) == "Cloud Nemotron"


def test_message_rendering_engine_is_none():
    msg = {"role": "assistant", "content": "Response", "engine": None, "model": None}
    assert resolve_engine_and_model_badge(msg) == "AIRA Assistant"
    if HAS_STREAMLIT and frontend_resolve_badge:
        assert frontend_resolve_badge(msg) == "AIRA Assistant"


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

    if HAS_STREAMLIT and frontend_resolve_badge:
        fe_badge = frontend_resolve_badge(msg)
        assert "Tool Assisted" in fe_badge
        assert "Local Gemma 2B" in fe_badge


def test_message_rendering_debug_traces():
    msg = {"role": "assistant", "content": "Resp", "model": "gemma:2b", "engine": "local"}
    badge_with_debug = resolve_engine_and_model_badge(msg, show_debug_traces=True)
    assert "`gemma:2b`" in badge_with_debug
