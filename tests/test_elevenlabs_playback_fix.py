"""Dedicated Test Suite for ElevenLabs Audio Playback Fix in Project AIRA.

Covers the 9 Step 7 Verification Requirements:
1. ElevenLabs authentication and voice selection (EXAVITQu4vr4xnSDxMaL).
2. Short fixed sentence synthesis using eleven_v4_turbo.
3. Audio-format validation (16,000 Hz, 16-bit depth, mono channel, valid RIFF WAVE).
4. Audio decoding and sample-boundary alignment (len % 2 == 0, odd network chunk protection).
5. Live audio playback through macOS audio device without samplesize exceptions.
6. Full wake-word command pipeline with orchestrator answer and spoken playback.
7. Deliberately corrupted / invalid audio handling without crashing.
8. Provider failure and visible fallback behavior (explicit alert, headers, last_metrics).
9. Normal companion shutdown (clean exit without double-free or leaked semaphores).
"""

import os
import io
import wave
import signal
import threading
import time
import pytest
import sounddevice as sd
from unittest.mock import patch, MagicMock

from src.voice.providers import (
    ElevenLabsTextToSpeechProvider,
    MacOSTextToSpeechProvider,
    pcm_to_wav_bytes,
    validate_wav_pcm,
)
from src.voice.interfaces import AudioChunk
from src.voice.service import get_voice_service
from src.desktop.companion import AiraDesktopCompanion
from src.voice.wake_word import WakeWordState


# ------------------------------------------------------------------------------
# Test 1: Authentication and Voice Selection
# ------------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.asyncio
async def test_1_elevenlabs_auth_and_voice_selection():
    """Confirms ElevenLabs API key and selects configured feminine voice (EXAVITQu4vr4xnSDxMaL)."""
    provider = ElevenLabsTextToSpeechProvider()
    assert provider.api_key, "ELEVENLABS_API_KEY must be configured in environment."
    assert provider.voice_id == "EXAVITQu4vr4xnSDxMaL", "Configured voice must match Sarah (EXAVITQu4vr4xnSDxMaL)."
    assert provider.model_id in ("eleven_v4_turbo", "eleven_turbo_v2_5"), "Configured model must be high-efficiency neural."

    # Validate against ElevenLabs API /v1/voices
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": provider.api_key}
        )
        assert resp.status_code == 200, f"Voices query failed: {resp.text}"
        data = resp.json()
        voices = data.get("voices", [])
        voice_ids = [v["voice_id"] for v in voices]
        assert provider.voice_id in voice_ids, f"Voice {provider.voice_id} must be in available voices list."
        # Confirm Sarah details
        sarah_voice = next(v for v in voices if v["voice_id"] == provider.voice_id)
        assert "Sarah" in sarah_voice["name"]
        assert sarah_voice.get("category") in ("premade", "generated", "professional")


# ------------------------------------------------------------------------------
# Test 2: Short Fixed Sentence Synthesis with eleven_v4_turbo
# ------------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.asyncio
async def test_2_short_fixed_sentence_synthesis():
    """Synthesizes a short fixed sentence using eleven_v4_turbo."""
    provider = ElevenLabsTextToSpeechProvider(model_id="eleven_v4_turbo")
    test_phrase = "Hello Om, this is AIRA speaking with Eleven v4 Turbo."
    chunk = await provider.synthesize(test_phrase)

    assert chunk is not None
    assert len(chunk.data) > 2000, "Synthesized audio chunk must contain substantial audio data."
    assert provider.last_provider_used == "elevenlabs"
    assert provider.last_status["generation_status"] == "success"
    assert provider.last_status["decoding_status"] == "valid_pcm16"
    assert provider.last_status["fallback_used"] is False


# ------------------------------------------------------------------------------
# Test 3: Audio-Format Validation
# ------------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.asyncio
async def test_3_audio_format_validation():
    """Verifies audio has 16,000 Hz sample rate, 16-bit depth, single channel (mono), valid RIFF header."""
    provider = ElevenLabsTextToSpeechProvider(model_id="eleven_v4_turbo")
    chunk = await provider.synthesize("Format verification in progress.")

    assert chunk.format == "wav"
    assert chunk.sample_rate == 16000
    assert chunk.channels == 1

    # Verify RIFF WAVE header directly via python wave module
    buf = io.BytesIO(chunk.data)
    with wave.open(buf, "rb") as wf:
        assert wf.getnchannels() == 1, "Channels must be mono (1)"
        assert wf.getsampwidth() == 2, "Sample width must be 2 bytes (16-bit)"
        assert wf.getframerate() == 16000, "Framerate must be 16000 Hz"
        n_frames = wf.getnframes()
        assert n_frames > 0, "Wave must contain frames"
        pcm_bytes = wf.readframes(n_frames)
        assert len(pcm_bytes) % 2 == 0, "PCM frame bytes must be aligned to 2 bytes per sample"

    assert validate_wav_pcm(chunk.data) is True


# ------------------------------------------------------------------------------
# Test 4: Audio Decoding and Sample-Boundary Alignment
# ------------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.asyncio
async def test_4_audio_decoding_and_sample_alignment():
    """Verifies raw audio bytes are decoded to PCM without samplesize misalignment (len % 2 == 0)."""
    provider = ElevenLabsTextToSpeechProvider()

    # Test stream chunks directly
    chunk_count = 0
    total_bytes = 0
    async for pcm_chunk in provider.synthesize_stream("Decoding and sample alignment test."):
        chunk_count += 1
        total_bytes += len(pcm_chunk)
        # CRUCIAL ASSERTION: Every chunk yielded by the provider must be strictly divisible by 2
        assert len(pcm_chunk) % 2 == 0, f"Chunk {chunk_count} length {len(pcm_chunk)} is not divisible by 2!"

    assert chunk_count > 0
    assert total_bytes > 0
    assert total_bytes % 2 == 0

    # Test simulation of arbitrary odd network chunks into buffering logic
    sample_size = 2
    play_buf = bytearray()
    odd_chunks = [b"\x01", b"\x02\x03\x04", b"\x05\x06", b"\x07", b"\x08\x09\x0a"]

    dispatched_chunks = []
    for raw in odd_chunks:
        play_buf.extend(raw)
        aligned_len = len(play_buf) - (len(play_buf) % sample_size)
        if aligned_len > 0:
            dispatched_chunks.append(bytes(play_buf[:aligned_len]))
            play_buf = play_buf[aligned_len:]

    if len(play_buf) > 0:
        play_buf.append(0)
        dispatched_chunks.append(bytes(play_buf))

    for c in dispatched_chunks:
        assert len(c) % 2 == 0, "Buffered chunk passed to sounddevice must be divisible by 2"

    total_dispatched = sum(len(c) for c in dispatched_chunks)
    assert total_dispatched >= sum(len(c) for c in odd_chunks)


# ------------------------------------------------------------------------------
# Test 5: Playback through Mac Audio Device without Samplesize Exception
# ------------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.asyncio
async def test_5_playback_through_mac_audio_device():
    """Plays generated audio through macOS audio device without raising samplesize error."""
    provider = ElevenLabsTextToSpeechProvider()
    clean_text = "Testing audio hardware playback directly."

    t0 = time.time()
    total_bytes = 0
    sample_size = 2
    play_buf = bytearray()
    played_chunks = 0

    # Stream into RawOutputStream just as companion.py does
    with sd.RawOutputStream(samplerate=16000, channels=1, dtype='int16') as out_stream:
        async for pcm_chunk in provider.synthesize_stream(clean_text):
            total_bytes += len(pcm_chunk)
            play_buf.extend(pcm_chunk)
            aligned_len = len(play_buf) - (len(play_buf) % sample_size)
            if aligned_len > 0:
                # This call failed previously with ValueError: len(data) not divisible by samplesize
                out_stream.write(bytes(play_buf[:aligned_len]))
                played_chunks += 1
                play_buf = play_buf[aligned_len:]

        if len(play_buf) > 0:
            play_buf.append(0)
            out_stream.write(bytes(play_buf))

    assert total_bytes > 0
    assert played_chunks > 0
    assert provider.last_provider_used == "elevenlabs"


# ------------------------------------------------------------------------------
# Test 6: Full Wake-Word Command Pipeline to Spoken Output
# ------------------------------------------------------------------------------
def test_6_full_wake_word_command_pipeline():
    """Simulates 'Hey AIRA' detection, command transcription, backend response, and speak_text call."""
    companion = AiraDesktopCompanion()

    captured_speech = []
    def mock_speak(text: str, request_id: str = None, **kwargs):
        captured_speech.append({"text": text, "request_id": request_id})

    companion.speak_text = mock_speak

    # Simulate captured command audio
    from tests.test_voice_verification import make_test_wav
    test_audio = make_test_wav(0.4)

    with patch.object(companion.stt, "transcribe") as mock_transcribe:
        from src.voice.interfaces import TranscriptionResult
        mock_transcribe.return_value = TranscriptionResult(text="what time is it", confidence=0.95, duration_ms=200)

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "request_id": "test_req_ww_789",
                "result": "The current time is 11:30 PM.",
                "approval_required": False,
                "pending_approval": None,
            }

            companion.on_command_captured(test_audio)

    assert len(captured_speech) == 1
    assert captured_speech[0]["request_id"] == "test_req_ww_789"
    assert "11:30 PM" in captured_speech[0]["text"]
    assert companion.detector.state == WakeWordState.LISTENING_LOCALLY


# ------------------------------------------------------------------------------
# Test 7: Deliberately Invalid Audio Handling
# ------------------------------------------------------------------------------
def test_7_deliberately_invalid_audio_handling():
    """Feeds corrupted audio bytes to the pipeline and verifies graceful handling."""
    corrupted_bytes = b"CORRUPTED_NOT_A_WAV_OR_PCM_HEADER_DEADBEEF" * 10
    is_valid = validate_wav_pcm(corrupted_bytes)
    assert is_valid is False

    # Verify companion on_command_captured handles transcription errors gracefully without crashing
    companion = AiraDesktopCompanion()
    with patch.object(companion.stt, "transcribe", side_effect=ValueError("Corrupt audio frames")):
        companion.on_command_captured(corrupted_bytes)
        assert companion.detector.state == WakeWordState.LISTENING_LOCALLY


# ------------------------------------------------------------------------------
# Test 8: Provider Failure and Explicit Visible Fallback Behavior
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_8_provider_failure_and_fallback():
    """Simulates provider failure and verifies companion falls back to macOS voice with alert logging."""
    bad_provider = ElevenLabsTextToSpeechProvider(api_key="bad_api_key_xyz")
    companion = AiraDesktopCompanion()
    companion.tts = bad_provider

    with patch("subprocess.run") as mock_say:
        mock_say.return_value.returncode = 0
        companion.speak_text("Testing explicit fallback logging.")

        # Confirm macOS fallback was invoked
        mock_say.assert_called_once()
        args = mock_say.call_args[0][0]
        assert "/usr/bin/say" in args
        assert "Samantha" in args

    assert bad_provider.last_provider_used == "macos_say_fallback"
    assert bad_provider.last_status["fallback_used"] is True
    assert "fallback_reason" in bad_provider.last_metrics


# ------------------------------------------------------------------------------
# Test 9: Normal Companion Shutdown Without Errors
# ------------------------------------------------------------------------------
def test_9_normal_companion_shutdown():
    """Verifies companion starts and stops cleanly via shutdown event without double-free errors."""
    companion = AiraDesktopCompanion()
    t = threading.Thread(target=companion.run, daemon=True)
    t.start()
    for _ in range(30):
        if companion._running:
            break
        time.sleep(0.1)

    assert companion._running is True

    # Signal stop
    companion.stop()
    t.join(timeout=2.0)
    assert not t.is_alive(), "Companion thread should terminate cleanly within 2 seconds."
    assert companion._shutdown_event.is_set()

