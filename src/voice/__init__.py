"""Voice interaction subsystem for AIRA."""

from .interfaces import (
    AudioChunk,
    TranscriptionResult,
    VoiceState,
    SpeechToTextProvider,
    TextToSpeechProvider,
    VoiceActivationDetector,
    ConversationTurnManager,
    MockSpeechToTextProvider,
    MockTextToSpeechProvider,
)
from .providers import (
    GoogleSpeechRecognitionSTTProvider,
    FasterWhisperSTTProvider,
    MacOSTextToSpeechProvider,
    FallbackTTSProvider,
    get_available_macos_voices,
)
from .service import (
    VoiceService,
    VoiceSessionManager,
    clean_text_for_speech,
    get_voice_service,
)

__all__ = [
    "AudioChunk",
    "TranscriptionResult",
    "VoiceState",
    "SpeechToTextProvider",
    "TextToSpeechProvider",
    "VoiceActivationDetector",
    "ConversationTurnManager",
    "MockSpeechToTextProvider",
    "MockTextToSpeechProvider",
    "GoogleSpeechRecognitionSTTProvider",
    "FasterWhisperSTTProvider",
    "MacOSTextToSpeechProvider",
    "FallbackTTSProvider",
    "get_available_macos_voices",
    "VoiceService",
    "VoiceSessionManager",
    "clean_text_for_speech",
    "get_voice_service",
]
