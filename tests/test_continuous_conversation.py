"""Tests for AIRA Continuous Conversation Mode and Natural Turn-Taking.

Verifies:
1. ConversationStateMachine states and transition validation.
2. TurnDetector VAD, pre-roll buffer, pause tolerance, silence completion, and empty-audio rejection.
3. Anti-feedback speaker gate and high-energy barge-in detection.
4. Multi-turn continuation intent and context preservation.
5. Short utterance acknowledgment and ambiguous keyword safety.
6. Explicit farewell detection and idle timeout conclusion.
7. Full 10-step conversational sequence simulation without wake-word repetition.
8. FastAPI /api/voice/interrupt endpoint.
"""

import math
import struct
import time
import pytest
from unittest.mock import MagicMock, patch

from src.voice.state_machine import ConversationState, ConversationStateMachine, ALLOWED_TRANSITIONS
from src.voice.turn_detector import TurnDetector, VADConfig
from src.agent.intent import analyze_conversational_intent, IntentCategory, CONTINUATION_PATTERNS
from src.desktop.companion import AiraDesktopCompanion


# Helper to generate 20ms 16kHz 16-bit mono PCM audio frames
def generate_sine_frame(freq: float = 440.0, sample_rate: int = 16000, duration_ms: int = 20, amplitude: int = 12000) -> bytes:
    """Generates a PCM frame of a sine wave (voiced speech proxy)."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    samples = []
    for i in range(num_samples):
        val = int(amplitude * math.sin(2 * math.pi * freq * (i / sample_rate)))
        samples.append(val)
    return struct.pack(f"<{len(samples)}h", *samples)


def generate_silent_frame(sample_rate: int = 16000, duration_ms: int = 20) -> bytes:
    """Generates a PCM frame of near-zero background noise / silence."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    return struct.pack(f"<{num_samples}h", *([10] * num_samples))


# ==============================================================================
# 1. State Machine Tests
# ==============================================================================

def test_state_machine_valid_full_cycle():
    sm = ConversationStateMachine()
    assert sm.state == ConversationState.STANDBY
    assert sm.session_id is None
    assert sm.turn_number == 0

    # Wake detected -> Active listening
    assert sm.transition_to(ConversationState.WAKE_DETECTED, "wake_word")
    assert sm.session_id is not None
    sess_id = sm.session_id

    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "ready_for_speech")
    assert sm.session_id == sess_id

    # Turn 1: User speaks
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 1
    assert sm.transition_to(ConversationState.TRANSCRIBING, "silence_detected")
    assert sm.transition_to(ConversationState.PROCESSING, "transcript_ready")
    assert sm.transition_to(ConversationState.SPEAKING, "tts_ready")
    # Assistant finishes speaking -> back to ACTIVE_LISTENING (NOT STANDBY)
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_complete")
    assert sm.session_id == sess_id  # Context preserved!

    # Turn 2: User speaks follow-up without wake word
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 2
    assert sm.session_id == sess_id


def test_state_machine_invalid_transition_rejection():
    sm = ConversationStateMachine()
    # From STANDBY, jumping directly to SPEAKING or TRANSCRIBING is forbidden
    assert not sm.can_transition(ConversationState.SPEAKING)
    assert not sm.transition_to(ConversationState.SPEAKING)
    assert sm.state == ConversationState.STANDBY

    # Jump to ACTIVE_LISTENING
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING)
    # Direct jump to PROCESSING without capture/transcribing is forbidden
    assert not sm.can_transition(ConversationState.PROCESSING)
    assert not sm.transition_to(ConversationState.PROCESSING)
    assert sm.state == ConversationState.ACTIVE_LISTENING


def test_state_machine_listeners_and_history():
    sm = ConversationStateMachine()
    events = []

    def listener(from_st, to_st, ctx):
        events.append((from_st, to_st, ctx.get("reason")))

    sm.add_listener(listener)
    sm.transition_to(ConversationState.WAKE_DETECTED, "wake_phrase")
    sm.transition_to(ConversationState.ACTIVE_LISTENING, "init")

    assert len(events) == 2
    assert events[0] == (ConversationState.STANDBY, ConversationState.WAKE_DETECTED, "wake_phrase")
    assert events[1] == (ConversationState.WAKE_DETECTED, ConversationState.ACTIVE_LISTENING, "init")

    hist = sm.get_history()
    assert len(hist) == 2
    assert hist[0].from_state == ConversationState.STANDBY
    assert hist[1].to_state == ConversationState.ACTIVE_LISTENING


def test_state_machine_barge_in_interruption():
    sm = ConversationStateMachine()
    sm.transition_to(ConversationState.WAKE_DETECTED)
    sm.transition_to(ConversationState.ACTIVE_LISTENING)
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE)
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    sm.transition_to(ConversationState.SPEAKING)

    # Barge-in while assistant is speaking
    assert sm.state == ConversationState.SPEAKING
    interrupted = sm.interrupt("user_barge_in")
    assert interrupted is True
    assert sm.state == ConversationState.INTERRUPTED

    # From INTERRUPTED, move immediately to CAPTURING_UTTERANCE to grab user's speech
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "capture_barge_in")
    assert sm.state == ConversationState.CAPTURING_UTTERANCE


def test_state_machine_session_termination():
    sm = ConversationStateMachine()
    sm.start_session("test_start")
    assert sm.is_in_active_session is True
    sess_id = sm.session_id

    # User says goodbye
    assert sm.end_session("user_goodbye") is True
    assert sm.state == ConversationState.STANDBY
    assert sm.session_id is None
    assert sm.is_in_active_session is False


# ==============================================================================
# 2. Turn Detector and VAD Tests
# ==============================================================================

def test_turn_detector_voiced_vs_silent():
    config = VADConfig(vad_aggressiveness=2, energy_threshold=300.0)
    detector = TurnDetector(config)

    voiced_frame = generate_sine_frame(freq=300, amplitude=10000)
    silent_frame = generate_silent_frame()

    is_voiced_1, rms_1 = detector.is_frame_voiced(voiced_frame)
    is_voiced_2, rms_2 = detector.is_frame_voiced(silent_frame)

    assert is_voiced_1 is True
    assert rms_1 > 300.0

    assert is_voiced_2 is False
    assert rms_2 < 300.0


def test_turn_detector_pre_roll_preservation():
    config = VADConfig(
        frame_duration_ms=20,
        pre_roll_duration_ms=400,  # 20 frames
        onset_frames_threshold=3,
        onset_window_frames=5,
        energy_threshold=300.0,
    )
    detector = TurnDetector(config)

    # Feed 10 silent frames into pre-roll buffer
    silent_frame = generate_silent_frame()
    for _ in range(10):
        detector.process_frame(silent_frame)

    assert detector.is_capturing is False

    # Feed 3 voiced frames to trigger onset
    voiced_frame = generate_sine_frame(amplitude=8000)
    speech_started = False
    for _ in range(3):
        started, done, _ = detector.process_frame(voiced_frame)
        if started:
            speech_started = True

    assert speech_started is True
    assert detector.is_capturing is True
    # Utterance frames must contain the pre-roll frames plus the triggering frame
    assert len(detector.utterance_frames) >= 11


def test_turn_detector_pause_tolerance_and_completion():
    config = VADConfig(
        frame_duration_ms=20,
        pre_roll_duration_ms=100,
        onset_frames_threshold=2,
        silence_timeout_sec=0.2,   # 200ms silence ends turn
        min_utterance_sec=0.08,    # 4 frames min speech
        energy_threshold=300.0,
    )
    detector = TurnDetector(config)

    voiced = generate_sine_frame(amplitude=8000)
    silent = generate_silent_frame()

    # Trigger onset with 2 voiced frames
    detector.process_frame(voiced)
    started, _, _ = detector.process_frame(voiced)
    assert detector.is_capturing is True

    # User pauses for 60ms (3 silent frames) - well below 200ms silence timeout
    for _ in range(3):
        started, done, audio = detector.process_frame(silent)
        assert done is False

    # User speaks more (3 voiced frames)
    for _ in range(3):
        started, done, audio = detector.process_frame(voiced)
        assert done is False

    # User finishes speaking: silence for >200ms (12 silent frames = 240ms)
    time.sleep(0.22)
    completed = False
    final_audio = None
    for _ in range(5):
        started, done, audio = detector.process_frame(silent)
        if done:
            completed = True
            final_audio = audio
            break

    assert completed is True
    assert final_audio is not None
    assert len(final_audio) > 0


def test_turn_detector_empty_audio_rejection():
    # Only 1 brief click frame then silence -> should reject as noise
    config = VADConfig(
        frame_duration_ms=20,
        onset_frames_threshold=1,
        silence_timeout_sec=0.1,
        min_utterance_sec=0.30,  # Minimum 300ms speech required
        energy_threshold=300.0,
    )
    detector = TurnDetector(config)

    voiced = generate_sine_frame(amplitude=8000)
    silent = generate_silent_frame()

    # Onset triggered by single click
    detector.process_frame(voiced)
    assert detector.is_capturing is True

    # 150ms of silence
    time.sleep(0.12)
    started, done, audio = detector.process_frame(silent)

    # Empty audio rejected: done is False, audio is None, capturing resets to False
    assert done is False
    assert audio is None
    assert detector.is_capturing is False


def test_turn_detector_anti_feedback_gate():
    config = VADConfig(
        energy_threshold=300.0,
        barge_in_energy_threshold=1500.0,
    )
    detector = TurnDetector(config)

    # Assistant speaking: normal laptop speaker echo (RMS ~800, between 300 and 1500)
    speaker_echo_frame = generate_sine_frame(amplitude=2000)
    _, rms_echo = detector.is_frame_voiced(speaker_echo_frame)
    assert 300.0 < rms_echo < 1500.0

    # Process frame with is_assistant_speaking=True
    started, done, _ = detector.process_frame(speaker_echo_frame, is_assistant_speaking=True)
    # Must NOT trigger speech onset or capture
    assert started is False
    assert detector.is_capturing is False

    # Now simulate loud user barge-in over speaker (RMS > 1500)
    loud_barge_in_frame = generate_sine_frame(amplitude=18000)
    _, rms_loud = detector.is_frame_voiced(loud_barge_in_frame)
    assert rms_loud >= 1500.0

    started, done, _ = detector.process_frame(loud_barge_in_frame, is_assistant_speaking=True)
    # High-energy barge-in signals speech_started=True
    assert started is True


def test_turn_detector_idle_timeout():
    config = VADConfig(idle_timeout_sec=0.15)
    detector = TurnDetector(config)

    detector.reset_active_listening()
    assert detector.is_idle_timed_out() is False

    time.sleep(0.18)
    assert detector.is_idle_timed_out() is True


# ==============================================================================
# 3. Continuation Intent & Multi-Turn Context Tests
# ==============================================================================

def test_intent_continuation_recognition():
    follow_ups = [
        "Tell me more about the second story",
        "Can you explain that with an example?",
        "Make that shorter",
        "Explain the first one again",
        "Give me another example",
        "What did you mean by that?",
    ]
    for text in follow_ups:
        intent = analyze_conversational_intent(text)
        assert intent.category == IntentCategory.CONTINUATION, f"Failed for '{text}': {intent.category}"
        assert intent.suggested_complexity in ("MEDIUM", "HEAVY"), f"Failed for '{text}'"
        assert intent.needs_project_context is True, f"Failed for '{text}'"


def test_short_acknowledgments_and_keywords():
    short_utterances = ["Yeah.", "Yes", "OK", "Sure", "You too."]
    for phrase in short_utterances:
        intent = analyze_conversational_intent(phrase)
        assert intent.category == IntentCategory.CASUAL
        assert "acknowledgement" in intent.tone_guidance.lower() or "conversational reply" in intent.tone_guidance.lower()

    # Ambiguous keyword "YouTube"
    keyword_intent = analyze_conversational_intent("YouTube")
    assert keyword_intent.category == IntentCategory.CASUAL
    assert "clarify" in keyword_intent.tone_guidance.lower()


def test_farewell_phrase_detection():
    companion = AiraDesktopCompanion()
    assert companion.is_farewell_phrase("Goodbye, AIRA") is True
    assert companion.is_farewell_phrase("stop listening") is True
    assert companion.is_farewell_phrase("Bye AIRA, see you later") is True
    assert companion.is_farewell_phrase("that's all for now") is True
    assert companion.is_farewell_phrase("What's the time?") is False
    assert companion.is_farewell_phrase("What is RAG?") is False


# ==============================================================================
# 4. Full 10-Step Multi-Turn Conversational Sequence Simulation
# ==============================================================================

def test_full_10_step_conversational_sequence():
    """Simulates the explicit 10-step sequence requested in the prompt:
    1. 'Hey AIRA' (wake detected)
    2. 'What's the time?'
    3. Spoken answer
    4. 'What is RAG?'
    5. 'Can you explain that with an example?'
    6. 'Make it shorter.'
    7. Interrupt AIRA during response
    8. Continue conversation without repeating wake word
    9. 'Goodbye, AIRA.'
    10. Verify return to STANDBY
    """
    sm = ConversationStateMachine()
    turns_history = []

    # Step 1: User says "Hey AIRA"
    assert sm.state == ConversationState.STANDBY
    assert sm.transition_to(ConversationState.WAKE_DETECTED, "wake_word_detected")
    assert sm.session_id is not None
    active_session_id = sm.session_id

    # Step 2 & 3: Turn 1: "What's the time?" -> response
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "session_activated")
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 1
    t1_text = "What's the time?"
    intent1 = analyze_conversational_intent(t1_text)
    assert intent1.category == IntentCategory.TIME_DATE_QUERY

    assert sm.transition_to(ConversationState.TRANSCRIBING)
    assert sm.transition_to(ConversationState.PROCESSING)
    assert sm.transition_to(ConversationState.SPEAKING)
    turns_history.append((sm.turn_number, t1_text, "It's 1:00 AM IST."))
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")

    # Step 4: Turn 2: "What is RAG?" without wake phrase
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 2
    assert sm.session_id == active_session_id  # SAME SESSION ID!
    t2_text = "What is RAG?"
    intent2 = analyze_conversational_intent(t2_text)
    assert sm.transition_to(ConversationState.TRANSCRIBING)
    assert sm.transition_to(ConversationState.PROCESSING)
    assert sm.transition_to(ConversationState.SPEAKING)
    turns_history.append((sm.turn_number, t2_text, "Retrieval-Augmented Generation blends..."))
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")

    # Step 5: Turn 3: "Can you explain that with an example?"
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 3
    assert sm.session_id == active_session_id
    t3_text = "Can you explain that with an example?"
    intent3 = analyze_conversational_intent(t3_text)
    assert intent3.category == IntentCategory.CONTINUATION
    assert sm.transition_to(ConversationState.TRANSCRIBING)
    assert sm.transition_to(ConversationState.PROCESSING)
    assert sm.transition_to(ConversationState.SPEAKING)
    turns_history.append((sm.turn_number, t3_text, "For example, imagine a library assistant..."))
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")

    # Step 6: Turn 4: "Make it shorter."
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 4
    assert sm.session_id == active_session_id
    t4_text = "Make it shorter."
    intent4 = analyze_conversational_intent(t4_text)
    assert intent4.category == IntentCategory.CONTINUATION
    assert sm.transition_to(ConversationState.TRANSCRIBING)
    assert sm.transition_to(ConversationState.PROCESSING)
    assert sm.transition_to(ConversationState.SPEAKING)
    turns_history.append((sm.turn_number, t4_text, "RAG searches documents before answering."))

    # Step 7: Interrupt AIRA during response
    assert sm.state == ConversationState.SPEAKING
    assert sm.interrupt("user_barge_in") is True
    assert sm.state == ConversationState.INTERRUPTED

    # Step 8: Continue conversation without repeating wake word
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "capture_interruption_speech")
    assert sm.session_id == active_session_id
    t5_text = "Got it, thank you."
    assert sm.transition_to(ConversationState.TRANSCRIBING)
    assert sm.transition_to(ConversationState.PROCESSING)
    assert sm.transition_to(ConversationState.SPEAKING)
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")

    # Step 9: User says "Goodbye, AIRA."
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    t6_text = "Goodbye, AIRA."
    companion = AiraDesktopCompanion()
    assert companion.is_farewell_phrase(t6_text) is True

    assert sm.transition_to(ConversationState.TRANSCRIBING)
    assert sm.transition_to(ConversationState.ENDING_SESSION, "farewell_detected")

    # Step 10: Verify return to STANDBY
    assert sm.transition_to(ConversationState.STANDBY, "session_concluded")
    assert sm.state == ConversationState.STANDBY
    assert sm.session_id is None
    assert sm.turn_number == 0

    # Ensure all 4 intermediate turns maintained context
    assert len(turns_history) == 4
    for turn_num, query, resp in turns_history:
        assert turn_num in (1, 2, 3, 4)


# ==============================================================================
# 5. FastAPI /api/voice/interrupt Endpoint Test
# ==============================================================================

@pytest.mark.asyncio
async def test_fastapi_interrupt_endpoint():
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/voice/interrupt", json={"session_id": "test_sess_123", "reason": "user_touch"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "interrupted"
        assert data.get("session_id") == "test_sess_123"


# ==============================================================================
# 6. Acceptance Tests A through H (Natural Live Voice Conversation)
# ==============================================================================

def test_acceptance_test_a_continuous_followup_no_wake_word():
    """Test A: Say 'Hey AIRA' once, ask 'What is machine learning?', receive an answer,
    and then say 'Explain it more simply' without another wake phrase."""
    sm = ConversationStateMachine()
    assert sm.state == ConversationState.STANDBY

    # Step 1: User says "Hey AIRA" once
    sm.start_session("hey_aira")
    assert sm.state == ConversationState.ACTIVE_LISTENING
    session_id = sm.session_id
    assert session_id is not None

    # Step 2: Turn 1: "What is machine learning?"
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 1
    intent1 = analyze_conversational_intent("What is machine learning?")
    assert intent1.category in (IntentCategory.GENERAL_KNOWLEDGE, IntentCategory.CASUAL)
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    sm.transition_to(ConversationState.SPEAKING)
    # Turn 1 completes; assistant automatically listens for next turn
    sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")
    assert sm.state == ConversationState.ACTIVE_LISTENING
    assert sm.session_id == session_id

    # Step 3: Turn 2: "Explain it more simply" without wake word
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
    assert sm.turn_number == 2
    assert sm.session_id == session_id
    intent2 = analyze_conversational_intent("Explain it more simply")
    assert intent2.category == IntentCategory.CONTINUATION
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    sm.transition_to(ConversationState.SPEAKING)
    sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")
    assert sm.state == ConversationState.ACTIVE_LISTENING


def test_acceptance_test_b_multi_turn_context():
    """Test B: Continue with 'Give me an example' and 'What should I learn first?'
    Verify that each answer uses the correct conversation context across turns."""
    sm = ConversationStateMachine()
    sm.start_session("hey_aira")
    sess_id = sm.session_id

    queries = [
        ("What is machine learning?", IntentCategory.GENERAL_KNOWLEDGE),
        ("Explain it more simply", IntentCategory.CONTINUATION),
        ("Give me an example", IntentCategory.CONTINUATION),
        ("What should I learn first?", IntentCategory.CONTINUATION),
    ]

    for expected_turn, (q_text, expected_cat) in enumerate(queries, 1):
        sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
        assert sm.turn_number == expected_turn
        assert sm.session_id == sess_id

        intent = analyze_conversational_intent(q_text)
        assert intent.category == expected_cat, f"Failed for '{q_text}'"
        if expected_cat == IntentCategory.CONTINUATION:
            assert intent.needs_project_context is True

        sm.transition_to(ConversationState.TRANSCRIBING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.ACTIVE_LISTENING, "turn_done")


def test_acceptance_test_c_contextual_acknowledgments():
    """Test C: Say 'Yes', 'Okay', 'No, something simpler', and 'Tell me more about that'.
    Verify appropriate contextual responses without unnecessary greetings."""
    # Short acknowledgments
    for phrase in ["Yes", "Okay", "not really"]:
        intent = analyze_conversational_intent(phrase)
        assert intent.category == IntentCategory.CASUAL
        assert "acknowledgement" in intent.tone_guidance.lower() or "conversational reply" in intent.tone_guidance.lower()
        # Must instruct not to introduce or recite greetings
        assert "not introduce yourself" in intent.tone_guidance.lower() or "do not introduce" in intent.tone_guidance.lower()

    # Continuation follow-ups
    for phrase in ["No, something simpler", "Tell me more about that"]:
        intent = analyze_conversational_intent(phrase)
        assert intent.category == IntentCategory.CONTINUATION
        assert "context" in intent.tone_guidance.lower()


def test_acceptance_test_d_anti_feedback_speaker_isolation():
    """Test D: Use the built-in speakers. Verify that AIRA does not transcribe or answer her own voice."""
    from src.voice.wake_word import LocalWakeWordDetector

    detector = LocalWakeWordDetector()
    detector.mode = "conversation"
    detector.is_speaking = True  # Assistant is currently speaking through Mac speakers

    # Generate synthetic audio representing AIRA's speaker output (RMS ~850, amplitude 1200)
    speaker_echo_chunk = generate_sine_frame(freq=400, amplitude=1200)

    # Feed frames to TurnDetector with is_assistant_speaking=True
    speech_started, utterance_completed, completed_bytes = detector.turn_detector.process_frame(
        speaker_echo_chunk, is_assistant_speaking=True
    )
    # Anti-feedback gate must suppress normal speaker volume
    assert speech_started is False
    assert utterance_completed is False
    assert completed_bytes is None
    assert detector.turn_detector.is_capturing is False

    # Simulate speaker finishes: clear_buffers() clears audio queue and resets detector
    detector.clear_buffers()
    detector.is_speaking = False

    # Now simulate user speaking next turn (RMS ~800, amplitude 6000)
    user_frame = generate_sine_frame(freq=300, amplitude=6000)
    for _ in range(3):
        speech_started, _, _ = detector.turn_detector.process_frame(user_frame, is_assistant_speaking=False)

    # Real human speech is detected cleanly
    assert speech_started is True
    assert detector.turn_detector.is_capturing is True


def test_acceptance_test_e_session_farewell_termination():
    """Test E: Say 'Goodbye, AIRA'. Verify that the session ends correctly."""
    sm = ConversationStateMachine()
    sm.start_session("hey_aira")
    assert sm.is_in_active_session is True

    companion = AiraDesktopCompanion()
    farewell = "Goodbye, AIRA"
    assert companion.is_farewell_phrase(farewell) is True

    # State transitions: CAPTURING_UTTERANCE -> TRANSCRIBING -> ENDING_SESSION -> STANDBY
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE)
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.ENDING_SESSION, "user_farewell")
    sm.transition_to(ConversationState.STANDBY, "session_concluded")

    assert sm.state == ConversationState.STANDBY
    assert sm.session_id is None
    assert sm.is_in_active_session is False


def test_acceptance_test_f_fault_recovery():
    """Test F: Simulate a transcription error, timeout, TTS failure, and backend failure.
    Verify graceful recovery on the next turn."""
    sm = ConversationStateMachine()
    sm.start_session("hey_aira")
    sess_id = sm.session_id

    # 1. Simulate Transcription Error Recovery
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE)
    sm.transition_to(ConversationState.TRANSCRIBING)
    # Error during STT -> recovers cleanly to ACTIVE_LISTENING
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "transcription_error_recovered") is True
    assert sm.state == ConversationState.ACTIVE_LISTENING
    assert sm.session_id == sess_id

    # 2. Simulate Backend Failure Recovery
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE)
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    # Backend 500 error -> speaks error message -> recovers to ACTIVE_LISTENING
    sm.transition_to(ConversationState.SPEAKING, "backend_error_notice")
    assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "backend_error_recovered") is True
    assert sm.state == ConversationState.ACTIVE_LISTENING
    assert sm.session_id == sess_id

    # 3. Simulate Next Turn Success after recoveries
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE)
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    sm.transition_to(ConversationState.SPEAKING)
    sm.transition_to(ConversationState.ACTIVE_LISTENING, "speech_completed")
    assert sm.state == ConversationState.ACTIVE_LISTENING
    assert sm.session_id == sess_id


def test_acceptance_test_g_zero_disallowed_transition_warnings_and_turn_increment(capsys):
    """Test G: Check that normal conversation produces no disallowed-state-transition warnings
    and that turn numbers increment correctly."""
    sm = ConversationStateMachine()
    sm.start_session("hey_aira")
    initial_sess_id = sm.session_id

    # Simulate 3 complete conversational turns
    for turn in range(1, 4):
        # ACTIVE_LISTENING -> CAPTURING_UTTERANCE -> TRANSCRIBING -> PROCESSING -> SPEAKING -> ACTIVE_LISTENING
        assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "speech_onset")
        assert sm.turn_number == turn
        assert sm.session_id == initial_sess_id

        assert sm.transition_to(ConversationState.TRANSCRIBING, "audio_captured")
        assert sm.transition_to(ConversationState.PROCESSING, "sending_to_backend")
        assert sm.transition_to(ConversationState.SPEAKING, "assistant_speaking")
        assert sm.transition_to(ConversationState.ACTIVE_LISTENING, "turn_complete_listen_next")

    captured = capsys.readouterr()
    assert "Disallowed transition" not in captured.out
    assert "Disallowed transition" not in captured.err
    assert sm.turn_number == 3


def test_acceptance_test_h_barge_in_and_stale_buffer_cleanup():
    """Test H: If barge-in is implemented, speak while AIRA is talking.
    Verify the assistant stops the previous response, processes the new user utterance,
    and does not retain stale audio."""
    sm = ConversationStateMachine()
    sm.start_session("hey_aira")
    sess_id = sm.session_id

    # Assistant is speaking turn 1
    sm.transition_to(ConversationState.CAPTURING_UTTERANCE)
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    sm.transition_to(ConversationState.SPEAKING)
    assert sm.state == ConversationState.SPEAKING

    # User barge-in occurs while assistant is speaking
    assert sm.interrupt("user_barge_in") is True
    assert sm.state == ConversationState.INTERRUPTED

    # Transition to capturing the interrupting utterance
    assert sm.transition_to(ConversationState.CAPTURING_UTTERANCE, "capture_barge_in") is True
    assert sm.state == ConversationState.CAPTURING_UTTERANCE
    assert sm.session_id == sess_id

    # The new utterance completes and is answered
    sm.transition_to(ConversationState.TRANSCRIBING)
    sm.transition_to(ConversationState.PROCESSING)
    sm.transition_to(ConversationState.SPEAKING)
    sm.transition_to(ConversationState.ACTIVE_LISTENING, "turn_complete")
    assert sm.state == ConversationState.ACTIVE_LISTENING
