"""Authoritative Conversation State Machine for AIRA.

Provides a unified lifecycle state machine for continuous, natural multi-turn
voice interaction, turn-taking, barge-in interruptions, and session termination.

States:
- STANDBY: Waiting for wake-word ('Hey AIRA').
- WAKE_DETECTED: Wake phrase confirmed, entering conversation session.
- ACTIVE_LISTENING: Conversational session active, VAD listening for user speech without wake word.
- CAPTURING_UTTERANCE: User is actively speaking; recording audio with pre-roll buffer.
- TRANSCRIBING: Transcribing captured utterance using on-device Faster-Whisper.
- PROCESSING: Sending to AIRA Orchestrator with multi-turn conversation context.
- SPEAKING: Streaming synthesized voice response (ElevenLabs / fallback).
- INTERRUPTED: User interrupted AIRA while she was speaking (barge-in).
- ENDING_SESSION: Session ending triggered by explicit farewell or idle timeout.
- ERROR: Voice hardware or network exception state.
"""

import time
import uuid
import threading
from enum import Enum
from typing import Optional, Callable, Dict, Any, List, Set
from dataclasses import dataclass, field


class ConversationState(str, Enum):
    """Explicit lifecycle states for continuous conversational voice interaction."""
    STANDBY = "standby"
    WAKE_DETECTED = "wake_detected"
    ACTIVE_LISTENING = "active_listening"
    CAPTURING_UTTERANCE = "capturing_utterance"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ENDING_SESSION = "ending_session"
    ERROR = "error"

    @property
    def label(self) -> str:
        labels = {
            self.STANDBY: "Standby — Waiting for 'Hey AIRA'",
            self.WAKE_DETECTED: "Wake Detected — Initializing Conversation",
            self.ACTIVE_LISTENING: "Active Conversation — Listening for Speech",
            self.CAPTURING_UTTERANCE: "Capturing Spoken Utterance",
            self.TRANSCRIBING: "Transcribing Speech",
            self.PROCESSING: "AIRA Orchestrator Processing",
            self.SPEAKING: "AIRA Speaking",
            self.INTERRUPTED: "Barge-in Interruption Detected",
            self.ENDING_SESSION: "Ending Conversation Session",
            self.ERROR: "Voice Service Error",
        }
        return labels.get(self, self.value)

    @property
    def icon(self) -> str:
        icons = {
            self.STANDBY: "👂",
            self.WAKE_DETECTED: "✨",
            self.ACTIVE_LISTENING: "🟢",
            self.CAPTURING_UTTERANCE: "🔴",
            self.TRANSCRIBING: "⚙️",
            self.PROCESSING: "🧠",
            self.SPEAKING: "🗣️",
            self.INTERRUPTED: "⚡",
            self.ENDING_SESSION: "👋",
            self.ERROR: "❌",
        }
        return icons.get(self, "ℹ️")


# Define explicit, strictly validated state transition graph
ALLOWED_TRANSITIONS: Dict[ConversationState, Set[ConversationState]] = {
    ConversationState.STANDBY: {
        ConversationState.WAKE_DETECTED,
        ConversationState.ACTIVE_LISTENING,  # Direct manual / UI trigger
        ConversationState.ERROR,
    },
    ConversationState.WAKE_DETECTED: {
        ConversationState.ACTIVE_LISTENING,
        ConversationState.CAPTURING_UTTERANCE,  # Utterance followed wake word immediately
        ConversationState.STANDBY,              # Cancelled / false alarm
        ConversationState.ERROR,
    },
    ConversationState.ACTIVE_LISTENING: {
        ConversationState.CAPTURING_UTTERANCE,  # User started speaking
        ConversationState.TRANSCRIBING,         # Resilient: captured audio ready for transcription
        ConversationState.INTERRUPTED,          # User stopped / cancelled
        ConversationState.ENDING_SESSION,       # Idle timeout or goodbye
        ConversationState.STANDBY,              # Stopped / disabled
        ConversationState.ERROR,
    },
    ConversationState.CAPTURING_UTTERANCE: {
        ConversationState.TRANSCRIBING,         # Silence detected; end of turn
        ConversationState.ACTIVE_LISTENING,     # Empty or noise-only audio; aborted
        ConversationState.INTERRUPTED,          # Cancelled during capture
        ConversationState.ENDING_SESSION,       # Session ended
        ConversationState.ERROR,
    },
    ConversationState.TRANSCRIBING: {
        ConversationState.PROCESSING,           # Speech transcribed successfully
        ConversationState.ACTIVE_LISTENING,     # Empty transcription; recover and re-listen
        ConversationState.ENDING_SESSION,       # Explicit exit command transcribed
        ConversationState.INTERRUPTED,          # Interrupted during transcription
        ConversationState.ERROR,
    },
    ConversationState.PROCESSING: {
        ConversationState.SPEAKING,             # Response generated, ready to speak
        ConversationState.ACTIVE_LISTENING,     # Direct completion with no speech needed
        ConversationState.INTERRUPTED,          # Interrupted during processing
        ConversationState.ENDING_SESSION,       # Session stopped during processing
        ConversationState.ERROR,
    },
    ConversationState.SPEAKING: {
        ConversationState.ACTIVE_LISTENING,     # Playback finished normally; listen for next turn!
        ConversationState.INTERRUPTED,          # Barge-in: user spoke over AIRA
        ConversationState.ENDING_SESSION,       # Finished parting message / goodbye
        ConversationState.STANDBY,              # Direct stop
        ConversationState.ERROR,
    },
    ConversationState.INTERRUPTED: {
        ConversationState.CAPTURING_UTTERANCE,  # Transition to recording the interrupting speech
        ConversationState.ACTIVE_LISTENING,     # Ready to listen for new turn
        ConversationState.ENDING_SESSION,       # Interruption was a stop command
        ConversationState.STANDBY,              # Direct return to standby
        ConversationState.ERROR,
    },
    ConversationState.ENDING_SESSION: {
        ConversationState.STANDBY,              # Cleanup complete; resume wake-word listening
        ConversationState.ERROR,
    },
    ConversationState.ERROR: {
        ConversationState.STANDBY,              # Reset from error to standby
        ConversationState.ACTIVE_LISTENING,     # Recover back to active conversation
        ConversationState.ENDING_SESSION,       # Graceful shutdown from error
    },
}


@dataclass
class StateTransitionRecord:
    from_state: ConversationState
    to_state: ConversationState
    timestamp: float
    session_id: Optional[str]
    turn_number: int
    reason: str


class ConversationStateMachine:
    """Authoritative lifecycle state machine for continuous multi-turn voice sessions.

    Guarantees:
    - Thread-safe state transitions validated against ALLOWED_TRANSITIONS.
    - Persistent session_id across all conversational turns in an active session.
    - Turn number tracking for context continuity.
    - Comprehensive transition listener callbacks and transition history.
    """

    def __init__(self):
        self._state: ConversationState = ConversationState.STANDBY
        self._session_id: Optional[str] = None
        self._turn_number: int = 0
        self._lock = threading.RLock()
        self._listeners: List[Callable[[ConversationState, ConversationState, Dict[str, Any]], None]] = []
        self._history: List[StateTransitionRecord] = []
        self._state_entered_time: float = time.time()

    @property
    def state(self) -> ConversationState:
        with self._lock:
            return self._state

    @property
    def session_id(self) -> Optional[str]:
        with self._lock:
            return self._session_id

    @property
    def turn_number(self) -> int:
        with self._lock:
            return self._turn_number

    @property
    def is_in_active_session(self) -> bool:
        """Returns True if the assistant is in an ongoing multi-turn session."""
        with self._lock:
            return self._state not in (
                ConversationState.STANDBY,
                ConversationState.ENDING_SESSION,
                ConversationState.ERROR,
            )

    @property
    def time_in_current_state(self) -> float:
        with self._lock:
            return time.time() - self._state_entered_time

    def can_transition(self, target_state: ConversationState) -> bool:
        """Checks if a transition from the current state to target_state is permitted."""
        with self._lock:
            allowed = ALLOWED_TRANSITIONS.get(self._state, set())
            return target_state in allowed

    def transition_to(
        self,
        target_state: ConversationState,
        reason: str = "",
        force: bool = False,
    ) -> bool:
        """Executes a validated transition to target_state with listener notifications.

        Args:
            target_state: Desired destination state.
            reason: Human-readable diagnostic rationale for the transition.
            force: If True, bypasses validation (for emergency resets/errors only).

        Returns:
            True if transition succeeded, False if disallowed.
        """
        with self._lock:
            from_state = self._state

            if from_state == target_state:
                return True  # Idempotent no-op

            if not force and not self.can_transition(target_state):
                session_tag = f" [Session: {self._session_id} | Turn: {self._turn_number}]" if self._session_id else ""
                print(f"⚠️ [StateMachine] Disallowed transition: {from_state.value} -> {target_state.value}{session_tag} (Reason: {reason})")
                return False

            # Update session lifecycle
            if from_state == ConversationState.STANDBY and target_state in (
                ConversationState.WAKE_DETECTED,
                ConversationState.ACTIVE_LISTENING,
            ):
                # Start new multi-turn voice session
                self._session_id = f"voice_sess_{uuid.uuid4().hex[:10]}"
                self._turn_number = 0

            elif target_state == ConversationState.STANDBY:
                # End of session
                self._session_id = None
                self._turn_number = 0

            if target_state == ConversationState.CAPTURING_UTTERANCE and from_state != ConversationState.INTERRUPTED:
                self._turn_number += 1

            now = time.time()
            self._state = target_state
            self._state_entered_time = now

            record = StateTransitionRecord(
                from_state=from_state,
                to_state=target_state,
                timestamp=now,
                session_id=self._session_id,
                turn_number=self._turn_number,
                reason=reason,
            )
            self._history.append(record)

            # Keep bounded history (last 100 transitions)
            if len(self._history) > 100:
                self._history.pop(0)

            # Diagnostic logging
            session_tag = f" [Session: {self._session_id} | Turn: {self._turn_number}]" if self._session_id else ""
            reason_tag = f" ({reason})" if reason else ""
            print(f"🔄 [StateMachine] {from_state.icon} {from_state.value} ➔ {target_state.icon} {target_state.value}{session_tag}{reason_tag}")

            # Notify registered listeners
            context = {
                "session_id": self._session_id,
                "turn_number": self._turn_number,
                "reason": reason,
                "timestamp": now,
            }
            for listener in list(self._listeners):
                try:
                    listener(from_state, target_state, context)
                except Exception as e:
                    print(f"⚠️ [StateMachine] Error in transition listener: {e}")

            return True

    def add_listener(
        self,
        listener: Callable[[ConversationState, ConversationState, Dict[str, Any]], None],
    ) -> None:
        """Registers a callback for state transition events."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(
        self,
        listener: Callable[[ConversationState, ConversationState, Dict[str, Any]], None],
    ) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def start_session(self, reason: str = "wake_word_detected") -> bool:
        """Transitions from STANDBY into active conversational listening."""
        if self._state == ConversationState.STANDBY:
            if self.transition_to(ConversationState.WAKE_DETECTED, reason=reason):
                return self.transition_to(ConversationState.ACTIVE_LISTENING, reason="session_activated")
        elif self._state == ConversationState.WAKE_DETECTED:
            return self.transition_to(ConversationState.ACTIVE_LISTENING, reason="session_activated")
        return False

    def interrupt(self, reason: str = "barge_in") -> bool:
        """Handles user barge-in during speaking, transcribing, or processing."""
        with self._lock:
            if self._state in (
                ConversationState.SPEAKING,
                ConversationState.PROCESSING,
                ConversationState.TRANSCRIBING,
            ):
                return self.transition_to(ConversationState.INTERRUPTED, reason=reason)
            return False

    def end_session(self, reason: str = "user_farewell") -> bool:
        """Gracefully ends active multi-turn conversation and returns to STANDBY."""
        with self._lock:
            if self._state in (ConversationState.STANDBY, ConversationState.ENDING_SESSION):
                return True
            if self.transition_to(ConversationState.ENDING_SESSION, reason=reason):
                return self.transition_to(ConversationState.STANDBY, reason="session_concluded")
            return False

    def reset_to_standby(self, reason: str = "reset") -> None:
        """Forcefully resets state machine to clean STANDBY state."""
        with self._lock:
            self.transition_to(ConversationState.STANDBY, reason=reason, force=True)

    def get_history(self) -> List[StateTransitionRecord]:
        with self._lock:
            return list(self._history)

