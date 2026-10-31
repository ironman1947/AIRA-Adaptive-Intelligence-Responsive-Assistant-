"""Configurable Voice Activity Detection (VAD) and Turn Detection for AIRA.

Provides:
- Dual-layer speech discrimination: WebRTC VAD + RMS energy floor.
- Short audio pre-roll ring buffer (300-500ms) to prevent syllable clipping.
- Speech-onset detection with noise/click filtering.
- Intra-sentence pause tolerance (200-600ms thinking pauses).
- End-of-utterance silence detection (configurable, default 1.1s).
- Maximum utterance duration safeguard (default 15.0s).
- Empty audio and background noise rejection.
- Continuous idle timeout tracking for automatic session ending.
"""

import time
import math
import struct
from collections import deque
from typing import Optional, List, Tuple
from dataclasses import dataclass


try:
    import webrtcvad
    _HAS_WEBRTC_VAD = True
except ImportError:
    webrtcvad = None
    _HAS_WEBRTC_VAD = False


@dataclass
class VADConfig:
    sample_rate: int = 16000
    frame_duration_ms: int = 20           # 20ms = 320 samples = 640 bytes @ 16kHz
    vad_aggressiveness: int = 2           # 0 (least aggressive) to 3 (most aggressive)
    energy_threshold: float = 320.0       # Minimum RMS energy to qualify as speech
    pre_roll_duration_ms: int = 400       # Pre-roll ring buffer before speech onset
    onset_frames_threshold: int = 3       # Consecutive/majority speech frames to trigger onset
    onset_window_frames: int = 5          # Window size to evaluate onset (e.g. 3 of 5 frames)
    silence_timeout_sec: float = 0.85     # End-of-utterance silence duration (tuned to 850ms, in 700-1000ms range)
    min_utterance_sec: float = 0.28       # Minimum speech duration to prevent empty rejection
    max_utterance_sec: float = 15.0       # Maximum continuous utterance duration
    idle_timeout_sec: float = 25.0        # Silence timeout before ending conversation session
    barge_in_energy_threshold: float = 2400.0  # RMS threshold for high-energy barge-in over speaker


class TurnDetector:
    """Detects speech onset, utterance capture, pause tolerance, and end-of-turn."""

    def __init__(self, config: Optional[VADConfig] = None):
        self.config = config or VADConfig()
        self.bytes_per_frame = int(self.config.sample_rate * 2 * (self.config.frame_duration_ms / 1000.0))

        # WebRTC VAD instance if available
        self._vad = None
        if _HAS_WEBRTC_VAD:
            try:
                self._vad = webrtcvad.Vad(self.config.vad_aggressiveness)
            except Exception as e:
                print(f"⚠️ [VAD] WebRTC VAD init error ({e}); using RMS energy gate fallback.")

        # Buffers
        num_pre_roll = max(1, int(self.config.pre_roll_duration_ms / self.config.frame_duration_ms))
        self._pre_roll_buffer = deque(maxlen=num_pre_roll)
        self._onset_window = deque(maxlen=self.config.onset_window_frames)

        # State tracking
        self.is_capturing = False
        self.utterance_frames: List[bytes] = []
        self.speech_frames_count = 0
        self.last_speech_time = time.time()
        self.utterance_start_time = 0.0
        self.active_listen_start_time = time.time()

    def reset_active_listening(self):
        """Prepares turn detector for listening for the user's next turn."""
        self.is_capturing = False
        self.utterance_frames.clear()
        self.speech_frames_count = 0
        self._onset_window.clear()
        now = time.time()
        self.last_speech_time = now
        self.utterance_start_time = 0.0
        self.active_listen_start_time = now

    def is_frame_voiced(self, frame_bytes: bytes) -> Tuple[bool, float]:
        """Classifies a single 20ms 16kHz PCM frame as voiced speech or silence/noise.

        Returns:
            (is_voiced, rms_energy)
        """
        if len(frame_bytes) < 4:
            return False, 0.0

        # Calculate RMS energy
        shorts = struct.unpack(f"<{len(frame_bytes)//2}h", frame_bytes)
        rms = math.sqrt(sum(s * s for s in shorts) / max(1, len(shorts)))

        # Layer 1: Energy floor check
        if rms < self.config.energy_threshold:
            return False, rms

        # Layer 2: WebRTC VAD spectral/statistical check
        if self._vad is not None and len(frame_bytes) == self.bytes_per_frame:
            try:
                is_speech = self._vad.is_speech(frame_bytes, self.config.sample_rate)
                return is_speech, rms
            except Exception:
                pass

        # Fallback if WebRTC VAD is unavailable or failed:
        # RMS above energy threshold qualifies
        return True, rms

    def process_frame(
        self,
        frame_bytes: bytes,
        is_assistant_speaking: bool = False,
    ) -> Tuple[bool, bool, Optional[bytes]]:
        """Processes an incoming 20ms audio frame against VAD state.

        Args:
            frame_bytes: 20ms chunk (640 bytes @ 16kHz 16-bit mono).
            is_assistant_speaking: True if the assistant is currently speaking via speaker.

        Returns:
            (speech_started, utterance_completed, completed_audio_bytes)
        """
        now = time.time()
        is_voiced, rms = self.is_frame_voiced(frame_bytes)

        # Anti-Feedback Gate: Suppress normal VAD speech onset during assistant playback
        # to prevent AIRA's speaker output from triggering false user turns.
        if is_assistant_speaking:
            # Check for high-energy barge-in (user talking loudly over speaker)
            if rms >= self.config.barge_in_energy_threshold:
                return True, False, None  # Signals barge-in attempt
            return False, False, None

        if not self.is_capturing:
            # IN ACTIVE_LISTENING STATE: Look for speech onset
            self._pre_roll_buffer.append(frame_bytes)
            self._onset_window.append(is_voiced)

            # Check if onset condition is met
            voiced_in_window = sum(1 for v in self._onset_window if v)
            if voiced_in_window >= self.config.onset_frames_threshold:
                # Speech onset detected!
                self.is_capturing = True
                self.utterance_start_time = now
                self.last_speech_time = now
                self.speech_frames_count = voiced_in_window

                # Seed utterance with pre-roll buffer so initial consonants/vowels are intact
                self.utterance_frames = list(self._pre_roll_buffer)
                self.utterance_frames.append(frame_bytes)
                self._onset_window.clear()
                return True, False, None

            return False, False, None

        else:
            # IN CAPTURING_UTTERANCE STATE: Recording user's turn
            self.utterance_frames.append(frame_bytes)

            if is_voiced:
                self.last_speech_time = now
                self.speech_frames_count += 1

            silence_duration = now - self.last_speech_time
            total_duration = now - self.utterance_start_time

            # Check for turn completion conditions:
            # Condition A: Silence duration exceeds threshold (user finished talking)
            # Condition B: Utterance reached maximum permitted length
            silence_done = (silence_duration >= self.config.silence_timeout_sec)
            max_duration_done = (total_duration >= self.config.max_utterance_sec)

            if silence_done or max_duration_done:
                total_audio = b"".join(self.utterance_frames)
                speech_duration = self.speech_frames_count * (self.config.frame_duration_ms / 1000.0)

                # Empty-Audio Rejection: Ensure user actually spoke rather than brief click
                if speech_duration < self.config.min_utterance_sec:
                    # Reject noise/click; resume active listening
                    self.reset_active_listening()
                    return False, False, None

                # Utterance successfully completed
                self.is_capturing = False
                completed_bytes = total_audio
                self.reset_active_listening()
                return False, True, completed_bytes

            return False, False, None

    def is_idle_timed_out(self) -> bool:
        """Returns True if no speech onset has occurred for idle_timeout_sec."""
        if self.is_capturing:
            return False
        return (time.time() - self.active_listen_start_time) >= self.config.idle_timeout_sec

