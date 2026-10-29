"""Voice Service and Session Manager for AIRA.

Provides high-level audio transcription, speech synthesis, spoken text
summarization (avoiding reading code/tables aloud), audio caching,
and privacy-aware provider dispatch.
"""

import os
import re
import hashlib
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv
load_dotenv()

from src.config import (
    AIRA_TTS_PROVIDER,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_TTS_MODEL,
)

from src.voice.interfaces import (
    AudioChunk,
    TranscriptionResult,
    VoiceState,
    SpeechToTextProvider,
    TextToSpeechProvider,
)
from src.voice.providers import (
    GoogleSpeechRecognitionSTTProvider,
    FasterWhisperSTTProvider,
    MacOSTextToSpeechProvider,
    ElevenLabsTextToSpeechProvider,
    FallbackTTSProvider,
)

def clean_text_for_speech(text: str, max_spoken_chars: int = 600) -> str:
    """Transforms written markdown into natural, speakable dialogue.

    Removes code blocks, markdown tables, URLs, excessive punctuation,
    and technical routing metadata so AIRA sounds natural when speaking aloud.
    """
    clean = text.strip()

    # 1. Replace multi-line code blocks with a natural spoken cue
    clean = re.sub(r"```[a-zA-Z]*\n[\s\S]*?```", " I've provided the code in our chat (code block omitted). ", clean)

    # 2. Replace markdown tables
    clean = re.sub(r"(\|.*\|\n)+", " I've formatted the data in our chat (data table omitted). ", clean)

    # 3. Replace Markdown links [Title](URL) with just Title
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)

    # 4. Remove bare URLs
    clean = re.sub(r"https?://[^\s\)]+", "", clean)

    # 5. Remove bold / italic / strike markdown symbols
    clean = re.sub(r"[*_~`#]", "", clean)

    # 6. Replace bullet points with pauses
    clean = re.sub(r"^\s*[-*]\s+", ". ", clean, flags=re.MULTILINE)

    # 7. Collapse multiple spaces and newlines
    clean = re.sub(r"\s+", " ", clean).strip()

    # 8. If text is excessively long, condense gently at sentence boundary
    if len(clean) > max_spoken_chars:
        cutoff = max(40, max_spoken_chars - 70)
        truncated = clean[:cutoff]
        last_period = truncated.rfind(". ")
        if last_period != -1 and last_period > 30:
            clean = truncated[:last_period + 1] + " I have prepared the complete detailed response in our chat."
        else:
            clean = truncated.strip() + "... I have prepared the complete detailed response in our chat."

    return clean

class VoiceService:
    """Coordinates STT and TTS across local and cloud providers with privacy enforcement."""

    def __init__(
        self,
        local_stt: Optional[SpeechToTextProvider] = None,
        remote_stt: Optional[SpeechToTextProvider] = None,
        tts_provider: Optional[TextToSpeechProvider] = None,
    ):
        self.local_stt = local_stt or FasterWhisperSTTProvider(model_size="tiny")
        try:
            self.remote_stt = remote_stt or GoogleSpeechRecognitionSTTProvider()
        except Exception:
            self.remote_stt = self.local_stt

        # TTS Provider: ElevenLabs Neural TTS if configured, else native macOS say or fallback
        tts_pref = (AIRA_TTS_PROVIDER or os.getenv("AIRA_TTS_PROVIDER", "elevenlabs")).lower()
        api_key = ELEVENLABS_API_KEY or os.getenv("ELEVENLABS_API_KEY", "")
        if tts_provider:
            self.tts = tts_provider
        elif tts_pref == "elevenlabs" and api_key:
            self.tts = ElevenLabsTextToSpeechProvider(
                api_key=api_key,
                voice_id=ELEVENLABS_VOICE_ID or os.getenv("ELEVENLABS_VOICE_ID"),
                model_id=ELEVENLABS_TTS_MODEL or os.getenv("ELEVENLABS_TTS_MODEL"),
            )
        elif os.path.exists("/usr/bin/say"):
            self.tts = MacOSTextToSpeechProvider()
        else:
            self.tts = FallbackTTSProvider()

        # In-memory audio cache: hash(text + voice) -> bytes
        self._tts_cache: Dict[str, bytes] = {}

    async def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        language: Optional[str] = None,
        privacy_mode: str = "standard",
    ) -> TranscriptionResult:
        """Transcribes incoming audio bytes to text, respecting privacy constraints."""
        if not audio_bytes:
            return TranscriptionResult(text="", confidence=0.0, is_final=True)

        audio_chunk = AudioChunk(data=audio_bytes, sample_rate=16000, channels=1, format="wav")

        # In Local-Only privacy mode, strictly use the local Whisper engine
        if privacy_mode == "local_only":
            print("🔒 [VoiceService] Enforcing Local-Only STT via Faster-Whisper")
            return await self.local_stt.transcribe(audio_chunk, language=language)

        # Standard mode: attempt remote provider first for fast multilingual latency, fallback to local
        try:
            return await self.remote_stt.transcribe(audio_chunk, language=language)
        except Exception as e:
            print(f"⚠️ [VoiceService] Remote STT failed ({e}); falling back to local Whisper...")
            return await self.local_stt.transcribe(audio_chunk, language=language)

    async def synthesize_speech(
        self,
        text: str,
        voice_style: Optional[str] = None,
        privacy_mode: str = "standard",
    ) -> AudioChunk:
        """Synthesizes text into spoken audio, using conversational text cleanup and caching."""
        spoken_text = clean_text_for_speech(text)
        if not spoken_text:
            return AudioChunk(data=b"", sample_rate=16000)

        cache_key = hashlib.md5(f"{spoken_text}:{voice_style}".encode()).hexdigest()
        if cache_key in self._tts_cache:
            return AudioChunk(data=self._tts_cache[cache_key], sample_rate=16000, channels=1, format="wav")

        audio_chunk = await self.tts.synthesize(spoken_text, voice_style=voice_style)
        if audio_chunk.data:
            self._tts_cache[cache_key] = audio_chunk.data

        return audio_chunk

    def stop_speech(self) -> None:
        """Immediately stops ongoing speech playback and cancels background say processes."""
        if hasattr(self.tts, "stop_all_speech"):
            self.tts.stop_all_speech()
        elif hasattr(MacOSTextToSpeechProvider, "stop_all_speech"):
            MacOSTextToSpeechProvider.stop_all_speech()

    def clear_cache(self) -> None:
        self._tts_cache.clear()

class VoiceSessionManager:
    """Manages active user voice states, pending transcripts, and language preferences."""

    def __init__(self, voice_service: Optional[VoiceService] = None):
        self.service = voice_service or VoiceService()
        self.state = VoiceState()
        self.selected_language: str = "auto"
        self.preferred_voice: str = "Samantha"
        self.voice_output_enabled: bool = True

    def set_language_preference(self, lang_code: str) -> None:
        self.selected_language = lang_code

    def set_voice_preference(self, voice_name: str) -> None:
        self.preferred_voice = voice_name

    def toggle_voice_output(self, enabled: bool) -> None:
        self.voice_output_enabled = enabled

    def interrupt_and_stop(self) -> None:
        """Cancels active speech output and resets voice state."""
        self.service.stop_speech()
        self.state.is_speaking = False
        self.state.is_listening = False


_shared_voice_service: Optional[VoiceService] = None

def get_voice_service() -> VoiceService:
    global _shared_voice_service
    if _shared_voice_service is None:
        _shared_voice_service = VoiceService()
    return _shared_voice_service
