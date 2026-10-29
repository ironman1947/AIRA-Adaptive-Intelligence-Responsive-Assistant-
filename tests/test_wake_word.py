"""Tests for AIRA Wake-Word Lifecycle and Interruption Handling."""

import pytest
import time
from src.voice.wake_word import WakeWordState, LocalWakeWordDetector, WakeWordEvent
from src.voice.providers import MacOSTextToSpeechProvider, convert_audio_to_pcm_wav


def test_wake_word_lifecycle_states():
    expected_states = [
        "wake_word_disabled",
        "initializing",
        "listening_locally",
        "wake_word_detected",
        "capturing_command",
        "recognizing_speech",
        "waiting_for_confirmation",
        "processing_request",
        "aira_speaking",
        "paused",
        "error",
    ]
    actual_states = [s.value for s in WakeWordState]
    for s in expected_states:
        assert s in actual_states, f"State {s} missing from WakeWordState"


def test_local_wake_word_detector_state_transitions():
    detector = LocalWakeWordDetector(wake_phrase="Hey AIRA")
    assert detector.state == WakeWordState.DISABLED

    recorded_states = []
    def on_change(st):
        recorded_states.append(st)

    detector._on_state_change = on_change
    detector.set_state(WakeWordState.INITIALIZING)
    detector.set_state(WakeWordState.LISTENING_LOCALLY)
    detector.set_state(WakeWordState.WAKE_WORD_DETECTED)
    detector.set_state(WakeWordState.CAPTURING_COMMAND)
    detector.set_state(WakeWordState.RECOGNIZING_SPEECH)
    detector.set_state(WakeWordState.PROCESSING_REQUEST)
    detector.set_state(WakeWordState.AIRA_SPEAKING)
    detector.set_state(WakeWordState.DISABLED)

    assert WakeWordState.LISTENING_LOCALLY in recorded_states
    assert WakeWordState.WAKE_WORD_DETECTED in recorded_states
    assert WakeWordState.AIRA_SPEAKING in recorded_states


def test_speech_interruption_stop():
    # Calling stop_all_speech terminates ongoing say processes without crashing
    MacOSTextToSpeechProvider.stop_all_speech()
    assert len(MacOSTextToSpeechProvider._active_processes) == 0


def test_convert_audio_to_pcm_wav_empty():
    with pytest.raises(ValueError, match="empty or too short"):
        convert_audio_to_pcm_wav(b"")
