"""Voice and conversational audio architecture interfaces for AIRA.

Provides clean abstractions for Speech-to-Text (STT), Text-to-Speech (TTS),
voice activation, and conversational turn management with interruption handling.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

@dataclass
class AudioChunk:
    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    format: str = "wav"

@dataclass
class TranscriptionResult:
    text: str
    confidence: float
    is_final: bool = True
    language: str = "en"
    duration_ms: float = 0.0
    sample_count: int = 0
    diagnostics: Optional[Dict[str, Any]] = None

@dataclass
class VoiceState:
    is_listening: bool = False
    is_speaking: bool = False
    wake_word_active: bool = False
    microphone_permission_granted: bool = False

class SpeechToTextProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: AudioChunk) -> TranscriptionResult:
        """Transcribes an audio chunk to text."""
        pass

class TextToSpeechProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice_style: Optional[str] = None) -> AudioChunk:
        """Synthesizes text into spoken audio."""
        pass

class VoiceActivationDetector(ABC):
    @abstractmethod
    def detect_wake_word(self, audio: AudioChunk) -> bool:
        """Detects whether AIRA's activation phrase was spoken."""
        pass

class ConversationTurnManager:
    """Manages conversational turns, microphone listening states, and cancellation."""
    def __init__(
        self,
        stt_provider: Optional[SpeechToTextProvider] = None,
        tts_provider: Optional[TextToSpeechProvider] = None,
    ):
        self.stt = stt_provider
        self.tts = tts_provider
        self.state = VoiceState()
        self._interrupted = False

    def request_microphone_access(self, granted: bool) -> None:
        self.state.microphone_permission_granted = granted

    def start_listening(self) -> bool:
        if not self.state.microphone_permission_granted:
            return False
        self.state.is_listening = True
        self._interrupted = False
        return True

    def stop_listening(self) -> None:
        self.state.is_listening = False

    def interrupt(self) -> None:
        """Interrupts spoken playback or listening immediately."""
        self._interrupted = True
        self.state.is_speaking = False
        self.state.is_listening = False

    def is_interrupted(self) -> bool:
        return self._interrupted

    def is_ready(self) -> bool:
        return True

class MockSpeechToTextProvider(SpeechToTextProvider):
    def __init__(self, preset_text: Optional[str] = None):
        self.preset_text = preset_text or "Hello AIRA, can you help me with this project?"

    async def transcribe(self, audio: AudioChunk, language: Optional[str] = None) -> TranscriptionResult:
        return TranscriptionResult(
            text=self.preset_text,
            confidence=0.98,
            is_final=True,
            language=language or "en",
            duration_ms=50.0,
        )

    def is_ready(self) -> bool:
        return True

class MockTextToSpeechProvider(TextToSpeechProvider):
    async def synthesize(self, text: str, voice_style: Optional[str] = None) -> AudioChunk:
        return AudioChunk(data=b"RIFF_MOCK_WAV_BYTES", sample_rate=16000)
