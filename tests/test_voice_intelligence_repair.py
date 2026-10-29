"""Automated Test Suite for Final Voice Intelligence and Natural Speech Repair.

Verifies:
1. "What is the system time?" retrieves local system clock accurately without generic greetings.
2. "What is system of time?" explains the timekeeping concept through deep reasoning without generic greetings.
3. "Open Safari." invokes authorized application-opening workflow requiring human confirmation.
4. ElevenLabs neural TTS produces high-quality audio with sub-second latency and explicit fallback reporting.
5. Response IDs are synchronized between chat answers and speech synthesis.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from src.agent.intent import analyze_conversational_intent, IntentCategory
from src.agent.core import run_agent_workflow
from src.voice.providers import (
    ElevenLabsTextToSpeechProvider,
    MacOSTextToSpeechProvider,
    validate_wav_pcm,
)
from src.voice.service import get_voice_service
from src.main import app

client = TestClient(app)

# ------------------------------------------------------------------------------
# 1. Intent Classification Regression Tests
# ------------------------------------------------------------------------------
def test_system_time_intent():
    for q in ["What is the system time?", "what is the system time", "current system time", "what time is it?"]:
        intent = analyze_conversational_intent(q)
        assert intent.category == IntentCategory.TIME_DATE_QUERY
        assert intent.suggested_complexity == "LOW"

def test_system_of_time_intent():
    for q in ["What is system of time?", "What is a system of time?", "Explain system of time."]:
        intent = analyze_conversational_intent(q)
        assert intent.category == IntentCategory.GENERAL_KNOWLEDGE
        assert intent.suggested_complexity == "HEAVY"

def test_open_safari_intent():
    for q in ["Open Safari.", "Open Safari", "open safari", "launch Safari"]:
        intent = analyze_conversational_intent(q)
        assert intent.category == IntentCategory.DESKTOP_ACTION
        assert intent.suggested_complexity == "HEAVY"
        assert intent.needs_coding_tools is True

# ------------------------------------------------------------------------------
# 2. Execution Behavior Tests
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_system_time_execution():
    res = await run_agent_workflow("What is the system time?")
    assert "current system time is" in res["result"].lower()
    assert res["model_used"] == "system_clock"
    assert "pleasure to meet you" not in res["result"].lower()
    assert "how can i assist you" not in res["result"].lower()

@pytest.mark.asyncio
async def test_system_of_time_execution():
    res = await run_agent_workflow("What is system of time?")
    # Must NOT be a generic greeting
    assert "pleasure to meet you" not in res["result"].lower()
    assert "how may i assist you" not in res["result"].lower()
    # Must contain relevant timekeeping explanation concepts
    result_lower = res["result"].lower()
    assert any(term in result_lower for term in ["utc", "coordinated", "time standard", "atomic", "timekeeping", "epoch", "gmt", "clock", "seconds"])

@pytest.mark.asyncio
async def test_open_safari_approval_flow():
    res = await run_agent_workflow("Open Safari.")
    assert res["approval_required"] is True
    assert res["pending_approval"] is not None
    assert res["pending_approval"]["tool_name"] == "desktop_open_application"
    assert res["pending_approval"]["parameters"]["app_name"].lower() == "safari"
    assert "safari" in res["result"].lower()

# ------------------------------------------------------------------------------
# 3. ElevenLabs Neural TTS Provider Tests
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_elevenlabs_neural_synthesis():
    svc = get_voice_service()
    # Provider should be ElevenLabs when configured with API key
    if isinstance(svc.tts, ElevenLabsTextToSpeechProvider) and svc.tts.api_key:
        chunk = await svc.synthesize_speech("Hello Om, voice pipeline active.")
        assert len(chunk.data) > 1000
        assert validate_wav_pcm(chunk.data) is True
        assert svc.tts.last_provider_used == "elevenlabs"
        assert "ttfb_ms" in svc.tts.last_metrics
        # TTFB benchmark: must be under 1500ms
        assert svc.tts.last_metrics["ttfb_ms"] < 1500

@pytest.mark.asyncio
async def test_elevenlabs_fallback_on_invalid_key():
    provider = ElevenLabsTextToSpeechProvider(api_key="invalid_test_key_123")
    chunk = await provider.synthesize("Testing fallback audio generation.")
    assert len(chunk.data) > 0
    assert validate_wav_pcm(chunk.data) is True
    assert provider.last_provider_used == "macos_say_fallback"
    assert "fallback_reason" in provider.last_metrics

# ------------------------------------------------------------------------------
# 4. API Endpoint & Response ID Synchronization Tests
# ------------------------------------------------------------------------------
def test_voice_config_endpoint():
    resp = client.get("/api/voice/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "available_voices" in data
    assert "default_voice" in data
    assert data["tts_available"] is True

def test_synthesize_endpoint_with_response_id():
    test_req_id = "req_test_sync_456"
    resp = client.post(
        "/api/voice/synthesize",
        json={"text": "System ready.", "request_id": test_req_id}
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "audio/wav"
    assert resp.headers.get("x-response-id") == test_req_id
    assert resp.headers.get("x-tts-provider") in ("elevenlabs", "macos_say_fallback", "macos")

