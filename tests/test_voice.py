"""Comprehensive Test Suite for AIRA Voice Intelligence Subsystem.

Tests:
1. Push-to-talk STT providers and audio chunk handling.
2. English, Hindi, and Marathi language parameter propagation.
3. Native macOS / Fallback TTS providers producing valid 16kHz WAV audio.
4. Conversational speech text cleaning (stripping code blocks, markdown tables, URLs).
5. Audio caching and cleanup.
6. Privacy mode enforcement (local_only strictly routes to local Faster-Whisper).
7. Honest error reporting without fabricated transcripts.
8. FastAPI voice endpoints (/api/voice/config, /api/voice/transcribe, /api/voice/synthesize).
"""

import io
import wave
import struct
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.voice.interfaces import (
    AudioChunk,
    TranscriptionResult,
    MockSpeechToTextProvider,
    MockTextToSpeechProvider,
)
from src.voice.providers import (
    MacOSTextToSpeechProvider,
    FallbackTTSProvider,
    get_available_macos_voices,
)
from src.voice.service import (
    VoiceService,
    clean_text_for_speech,
    get_voice_service,
)

client = TestClient(app)

def create_dummy_wav(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Generates a valid 16kHz 16-bit mono PCM WAV for audio tests."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        num_frames = int(sample_rate * duration_s)
        # Generate silence
        data = struct.pack(f"<{num_frames}h", *([0] * num_frames))
        wf.writeframes(data)
    return buf.getvalue()


class TestTextToSpeechCleaning:
    """Test natural conversational spoken text formatting."""

    def test_strip_markdown_code_blocks(self):
        text = "Here is the code:\n```python\nprint('hello world')\n```\nLet me know if you need edits."
        cleaned = clean_text_for_speech(text)
        assert "print('hello world')" not in cleaned
        assert "code block omitted" in cleaned
        assert "Let me know if you need edits" in cleaned

    def test_strip_markdown_tables(self):
        text = "Here are the metrics:\n| Metric | Score |\n| --- | --- |\n| Accuracy | 99% |\nOverall looking solid."
        cleaned = clean_text_for_speech(text)
        assert "| Metric | Score |" not in cleaned
        assert "Accuracy" not in cleaned
        assert "data table omitted" in cleaned
        assert "Overall looking solid" in cleaned

    def test_strip_markdown_links_to_plain_text(self):
        text = "Check the [FastAPI Documentation](https://fastapi.tiangolo.com) for details."
        cleaned = clean_text_for_speech(text)
        assert "https://fastapi.tiangolo.com" not in cleaned
        assert "FastAPI Documentation" in cleaned

    def test_condense_excessively_long_responses(self):
        long_paragraph = "This is a detailed analysis point. " * 30
        cleaned = clean_text_for_speech(long_paragraph, max_spoken_chars=150)
        assert len(cleaned) <= 180
        assert "I have prepared the complete detailed response in our chat" in cleaned


class TestSpeechSynthesis:
    """Test text-to-speech synthesis providers."""

    @pytest.mark.asyncio
    async def test_fallback_tts_produces_valid_wav(self):
        provider = FallbackTTSProvider()
        chunk = await provider.synthesize("Hello from AIRA")
        assert len(chunk.data) > 44  # WAV header is 44 bytes
        assert chunk.sample_rate == 16000
        assert chunk.format == "wav"

        # Verify WAV integrity
        with wave.open(io.BytesIO(chunk.data), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    @pytest.mark.asyncio
    async def test_macos_tts_voice_selection_devanagari(self):
        provider = MacOSTextToSpeechProvider()
        # English defaults to Samantha
        en_voice = provider.select_voice_for_text("Hello how are you?")
        assert en_voice == "Samantha"

        # Hindi Devanagari routes to Lekha
        hi_voice = provider.select_voice_for_text("नमस्ते, तुम्ही कसे आहात?")
        assert hi_voice == "Lekha"

        # Explicit user choice overrides script detection
        override_voice = provider.select_voice_for_text("Hello", user_voice_choice="Tara")
        assert override_voice == "Tara"

    def test_available_macos_voices_listing(self):
        voices = get_available_macos_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0
        voice_ids = [v["id"] for v in voices]
        assert "Samantha" in voice_ids or "Lekha" in voice_ids


class TestVoiceService:
    """Test the unified VoiceService coordinator."""

    @pytest.mark.asyncio
    async def test_voice_service_caching(self):
        mock_tts = MockTextToSpeechProvider()
        service = VoiceService(tts_provider=mock_tts)

        audio1 = await service.synthesize_speech("Test message for caching")
        audio2 = await service.synthesize_speech("Test message for caching")

        assert audio1.data == audio2.data
        # Cache should have 1 entry
        assert len(service._tts_cache) == 1

    @pytest.mark.asyncio
    async def test_local_only_privacy_routes_to_local_stt(self):
        mock_local = MockSpeechToTextProvider(preset_text="Local offline transcription")
        mock_remote = MockSpeechToTextProvider(preset_text="Remote cloud transcription")

        service = VoiceService(local_stt=mock_local, remote_stt=mock_remote)
        dummy_audio = create_dummy_wav(0.2)

        # In local_only mode, must call local_stt
        result = await service.transcribe_audio_bytes(dummy_audio, privacy_mode="local_only")
        assert result.text == "Local offline transcription"

    @pytest.mark.asyncio
    async def test_empty_audio_handling(self):
        service = get_voice_service()
        result = await service.transcribe_audio_bytes(b"")
        assert result.text == ""
        assert result.confidence == 0.0


class TestVoiceAPIEndpoints:
    """Test FastAPI Voice API endpoints."""

    def test_get_voice_config(self):
        resp = client.get("/api/voice/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "available_voices" in data
        assert "supported_languages" in data
        assert data["tts_available"] is True
        lang_codes = [l["code"] for l in data["supported_languages"]]
        assert "en" in lang_codes
        assert "hi" in lang_codes
        assert "mr" in lang_codes

    def test_synthesize_voice_endpoint(self):
        payload = {
            "text": "Hello, I am AIRA, your personal AI companion.",
            "voice_id": "Samantha",
            "summarize_for_speech": True,
        }
        resp = client.post("/api/voice/synthesize", json=payload)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        assert len(resp.content) > 44

    def test_transcribe_voice_empty_fails_gracefully(self):
        files = {"file": ("empty.wav", b"", "audio/wav")}
        data = {"language": "en", "privacy_mode": "standard"}
        resp = client.post("/api/voice/transcribe", files=files, data=data)
        assert resp.status_code == 400
        assert "Empty audio" in resp.json()["detail"]

    def test_transcribe_voice_with_dummy_wav(self):
        dummy_wav = create_dummy_wav(0.2)
        files = {"file": ("test.wav", dummy_wav, "audio/wav")}
        data = {"language": "en", "privacy_mode": "standard"}
        resp = client.post("/api/voice/transcribe", files=files, data=data)
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "provider_used" in data
        assert "duration_ms" in data

    def test_convert_audio_to_pcm_wav_decoding(self):
        from src.voice.providers import convert_audio_to_pcm_wav
        dummy = create_dummy_wav(0.3)
        res = convert_audio_to_pcm_wav(dummy, target_sample_rate=16000)
        assert len(res) > 44
        assert res[:4] == b"RIFF"
