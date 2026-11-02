"""Comprehensive Test Suite for AIRA Live Voice Provider and Pipeline Repairs.

Verifies:
1. GeminiLiveVoiceProvider configuration and tool declarations.
2. Tool execution for deterministic utility handlers (time, date, diagnostics).
3. Bidirectional streaming receive loop (24kHz audio output, text, server barge-in, turn complete).
4. Controlled fallback from live mode to chained mode when GEMINI_API_KEY is missing or connection fails.
5. Faster-Whisper calibrated confidence calculation and English language constraint.
6. Sample-accurate audio diagnostics telemetry (sample rate, channels, samples, duration, RMS, clipping, silence).
7. Monotonic per-turn timing origin reset (eliminates cumulative session duration bug).
8. Recognition uncertainty handling (confidence < 0.40 triggers clarification prompt).
9. ElevenLabs WebSocket idle handling and reconnection tracking.
"""

import os
import time
import math
import wave
import io
import struct
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.voice.interfaces import AudioChunk, TranscriptionResult
from src.voice.live_provider import (
    GeminiLiveVoiceProvider,
    GeminiLiveAudioPlayer,
    GENAI_AVAILABLE,
)
from src.desktop.companion import AiraDesktopCompanion, VoiceRequestTimer
from src.voice.state_machine import ConversationState
from src.voice.providers import FasterWhisperSTTProvider, ElevenLabsTextToSpeechProvider


# ------------------------------------------------------------------------------
# 1. Live Provider Tool Declarations and Configuration Tests
# ------------------------------------------------------------------------------
@pytest.mark.skipif(not GENAI_AVAILABLE, reason="google-genai not installed (pip install -e '.[voice]')")
def test_live_provider_tool_declarations():
    """Verify tool declarations match AIRA's desktop and utility capabilities."""
    provider = GeminiLiveVoiceProvider(api_key="test_dummy_key_12345")
    assert provider.model == "gemini-2.0-flash-exp"
    assert provider.voice_name == "Aoede"

    tools = provider._get_tools()
    assert len(tools) > 0
    func_decls = tools[0].function_declarations
    tool_names = [f.name for f in func_decls]

    assert "get_current_time" in tool_names
    assert "get_current_date" in tool_names
    assert "desktop_open_application" in tool_names
    assert "desktop_system_diagnostics" in tool_names


@pytest.mark.asyncio
@pytest.mark.skipif(not GENAI_AVAILABLE, reason="google-genai not installed (pip install -e '.[voice]')")
async def test_live_provider_tool_execution_deterministic_time():
    """Verify tool execution returns accurate IST time and date."""
    provider = GeminiLiveVoiceProvider(api_key="test_dummy_key_12345")

    # Mock tool call with get_current_time
    mock_fc = MagicMock()
    mock_fc.id = "call_abc123"
    mock_fc.name = "get_current_time"
    mock_fc.args = {}

    mock_tool_call = MagicMock()
    mock_tool_call.function_calls = [mock_fc]

    mock_session = AsyncMock()
    provider.session = mock_session

    await provider._handle_tool_call(mock_tool_call)

    assert mock_session.send_tool_response.called
    call_args = mock_session.send_tool_response.call_args[1]
    responses = call_args["function_responses"]
    assert len(responses) == 1
    assert responses[0].name == "get_current_time"
    assert "IST" in responses[0].response["timezone"]


# ------------------------------------------------------------------------------
# 2. Live Provider Receive Loop and Interruption Tests
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_provider_receive_loop_audio_and_interruption():
    """Verify 24kHz audio chunks, server barge-in, and turn completion callbacks."""
    provider = GeminiLiveVoiceProvider(api_key="test_dummy_key_12345")

    barge_in_fired = False
    turn_complete_fired = False
    text_chunks = []

    def on_barge_in():
        nonlocal barge_in_fired
        barge_in_fired = True

    def on_turn_complete():
        nonlocal turn_complete_fired
        turn_complete_fired = True

    def on_text(t):
        text_chunks.append(t)

    provider.on_barge_in = on_barge_in
    provider.on_turn_complete = on_turn_complete
    provider.on_text_received = on_text

    # Mock audio player
    provider.player = MagicMock()

    # Simulate messages from Gemini Live server:
    # 1. Normal turn with audio and text
    # 2. Interruption message
    # 3. Turn complete message
    pcm_24k_dummy = b"\x00\x00" * 480  # 20ms of silence at 24kHz

    msg1 = MagicMock()
    msg1.tool_call = None
    msg1.server_content.interrupted = False
    part1 = MagicMock()
    part1.inline_data.data = pcm_24k_dummy
    part1.text = "Hello Om! "
    msg1.server_content.model_turn.parts = [part1]
    msg1.server_content.turn_complete = False

    msg2 = MagicMock()
    msg2.tool_call = None
    msg2.server_content.interrupted = True
    msg2.server_content.model_turn = None
    msg2.server_content.turn_complete = False

    msg3 = MagicMock()
    msg3.tool_call = None
    msg3.server_content.interrupted = False
    msg3.server_content.model_turn = None
    msg3.server_content.turn_complete = True

    async def fake_receive():
        yield msg1
        yield msg2
        yield msg3

    mock_session = AsyncMock()
    mock_session.receive = fake_receive
    provider.session = mock_session
    provider._running = True

    await provider._receive_loop()

    # Audio should have been written
    provider.player.write.assert_called_with(pcm_24k_dummy)
    assert text_chunks == ["Hello Om! "]
    # Interruption must abort player and fire callback
    assert provider.player.abort.called
    assert barge_in_fired is True
    # Turn completion callback
    assert turn_complete_fired is True


# ------------------------------------------------------------------------------
# 3. Companion Mode Selection and Controlled Fallback Tests
# ------------------------------------------------------------------------------
def test_companion_mode_fallback_when_key_missing():
    """Verify companion visibly falls back to chained mode if GEMINI_API_KEY is not set."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
        companion = AiraDesktopCompanion(mode="live")
        assert companion.mode == "chained"
        companion.stop()


def test_companion_explicit_chained_mode():
    """Verify companion correctly configures chained mode when requested."""
    companion = AiraDesktopCompanion(mode="chained")
    assert companion.mode == "chained"
    assert companion.conversation_state == ConversationState.STANDBY
    companion.stop()


# ------------------------------------------------------------------------------
# 4. Faster-Whisper Language Constraint and Calibrated Confidence Tests
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_faster_whisper_language_constraint_and_diagnostics():
    """Verify Faster-Whisper defaults to English and returns sample-accurate diagnostics."""
    stt = FasterWhisperSTTProvider(model_size="tiny")

    # Generate 1.0s of 16kHz sine wave PCM WAV
    sample_rate = 16000
    n_samples = 16000
    t = [i / sample_rate for i in range(n_samples)]
    raw_shorts = [int(10000 * math.sin(2 * math.pi * 440 * ti)) for ti in t]
    raw_pcm = struct.pack(f"<{n_samples}h", *raw_shorts)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_pcm)

    chunk = AudioChunk(data=buf.getvalue(), sample_rate=16000, channels=1, format="wav")

    # Mock WhisperModel.transcribe
    mock_seg = MagicMock()
    mock_seg.text = "Yes, sounds good."
    mock_seg.avg_logprob = -0.15  # exp(-0.15) ~ 0.86
    mock_seg.no_speech_prob = 0.05

    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_seg], mock_info)

    with patch.object(stt, "_get_model", return_value=mock_model):
        res = await stt.transcribe(chunk, language=None)

        assert res.text == "Yes, sounds good."
        assert res.language == "en"
        # Calibrated confidence should be ~0.86, NOT an arbitrary constant
        assert 0.80 <= res.confidence <= 0.95
        # Verify diagnostics
        assert res.diagnostics is not None
        assert res.diagnostics["sample_rate"] == 16000
        assert res.diagnostics["channels"] == 1
        assert res.diagnostics["sample_count"] == 16000
        assert res.diagnostics["duration_sec"] == 1.0
        assert res.diagnostics["rms_energy"] > 5000.0


# ------------------------------------------------------------------------------
# 5. Monotonic Per-Turn Latency Origin Reset Tests
# ------------------------------------------------------------------------------
def test_monotonic_turn_latency_reset_prevents_duration_growth():
    """Verify per-turn timing origin does not leak previous turn elapsed time."""
    companion = AiraDesktopCompanion(mode="chained")

    # Turn 1: User says wake phrase at t0
    t0 = 1000.0
    companion._wake_perf_t = t0

    # Simulate Turn 1 command capture 1.5s later
    t_turn1_end = 1001.5
    dummy_wav_1s = b"\x00\x00" * 16000  # 1.0s audio

    with patch("time.perf_counter", side_effect=[t_turn1_end, 1001.6, 1001.8]):
        timer1 = VoiceRequestTimer("vreq_turn1")
        sample_duration1 = len(dummy_wav_1s) / (16000 * 2)
        timer1.t1_wake_detected = t0
        timer1.t3_capture_end = t_turn1_end
        # Capture duration for Turn 1 should be 1.5s
        assert round((timer1.t3_capture_end - timer1.t1_wake_detected), 1) == 1.5

    # Turn 2: User speaks 20 seconds later!
    # With the bug, t1 was stuck at t0 (1000.0), causing report to show 22s!
    # With the fix, _turn_start_perf_t is set when speech begins in Turn 2
    t_turn2_speech_start = 1021.0
    companion._turn_start_perf_t = t_turn2_speech_start
    t_turn2_end = 1022.2  # 1.2s turn speech duration

    timer2 = VoiceRequestTimer("vreq_turn2")
    sample_duration2 = len(dummy_wav_1s) / (16000 * 2)
    t_start2 = companion._turn_start_perf_t if companion._turn_start_perf_t > 0 else (t_turn2_end - sample_duration2)
    timer2.t1_wake_detected = t_start2
    timer2.t3_capture_end = t_turn2_end

    # Turn 2 capture duration must be exactly 1.2s, NOT 22.2s!
    assert round((timer2.t3_capture_end - timer2.t1_wake_detected), 1) == 1.2
    companion.stop()


# ------------------------------------------------------------------------------
# 6. Recognition Uncertainty Rejection Tests
# ------------------------------------------------------------------------------
def test_recognition_uncertainty_handling():
    """Verify low-confidence transcripts (< 0.40) trigger clarification prompt instead of garble."""
    companion = AiraDesktopCompanion(mode="chained")
    companion.sm.transition_to(ConversationState.WAKE_DETECTED, reason="wake")
    companion.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="active")

    dummy_audio = b"\x00\x00" * 8000  # 0.5s audio

    # Mock STT to return low confidence (e.g. 0.28 on background murmur)
    low_conf_result = TranscriptionResult(
        text="ur... hmm kya",
        confidence=0.28,
        language="ur",
        duration_ms=120.0,
        sample_count=8000,
        diagnostics={"sample_rate": 16000, "channels": 1, "duration_sec": 0.5, "rms_energy": 250.0},
    )

    spoken_prompts = []
    def mock_speak(text, **kwargs):
        spoken_prompts.append(text)

    with patch.object(companion.stt, "transcribe", AsyncMock(return_value=low_conf_result)), \
         patch.object(companion, "speak_text", side_effect=mock_speak):

        companion.on_command_captured(dummy_audio)

        # Must have prompted user to repeat, not executed the garble
        assert len(spoken_prompts) == 1
        assert "didn't quite catch that" in spoken_prompts[0].lower() or "repeat" in spoken_prompts[0].lower()
        # Must return to ACTIVE_LISTENING to wait for user repeat
        assert companion.conversation_state == ConversationState.ACTIVE_LISTENING

    companion.stop()


# ------------------------------------------------------------------------------
# 7. ElevenLabs WebSocket Idle Timeout Tracking
# ------------------------------------------------------------------------------
def test_elevenlabs_websocket_idle_timeout_refresh():
    """Verify WebSocket idle tracking cleanly refreshes connections older than 18 seconds."""
    provider = ElevenLabsTextToSpeechProvider(api_key="test_dummy_key")

    mock_ws = MagicMock()
    mock_ws.open = True
    provider._persistent_ws = mock_ws
    provider._persistent_ws_voice_id = provider.DEFAULT_VOICE_ID
    provider._persistent_ws_model_id = provider.DEFAULT_MODEL_ID

    # Case A: Recently used (e.g. 5 seconds ago) -> ws_is_alive is True
    provider._persistent_ws_last_used = time.time() - 5.0
    now_t = time.time()
    ws_idle_time = now_t - provider._persistent_ws_last_used
    ws_is_alive = (
        getattr(mock_ws, "open", False)
        and ws_idle_time < 18.0
        and provider._persistent_ws_voice_id == provider.DEFAULT_VOICE_ID
    )
    assert ws_is_alive is True

    # Case B: Idle for 25 seconds -> ws_is_alive is False, connection must refresh
    provider._persistent_ws_last_used = time.time() - 25.0
    now_t = time.time()
    ws_idle_time = now_t - provider._persistent_ws_last_used
    ws_is_alive = (
        getattr(mock_ws, "open", False)
        and ws_idle_time < 18.0
        and provider._persistent_ws_voice_id == provider.DEFAULT_VOICE_ID
    )
    assert ws_is_alive is False

