"""Local On-Device Wake-Word Detection Subsystem for AIRA.

Provides:
- WakeWordState: Explicit lifecycle states as defined in the specification.
- WakeWordDetector: Abstract provider interface for replaceable detectors.
- LocalWakeWordDetector: 100% on-device continuous keyword spotter for "Hey AIRA"
  with VAD, speech-end detection, and command capture. Zero cloud ambient audio streaming.
"""

import os
import time
import math
import struct
import threading
from enum import Enum
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass


class WakeWordState(str, Enum):
    """Explicit lifecycle states for hands-free wake-word operation."""
    DISABLED = "wake_word_disabled"
    INITIALIZING = "initializing"
    LISTENING_LOCALLY = "listening_locally"
    WAKE_WORD_DETECTED = "wake_word_detected"
    CAPTURING_COMMAND = "capturing_command"
    RECOGNIZING_SPEECH = "recognizing_speech"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    PROCESSING_REQUEST = "processing_request"
    AIRA_SPEAKING = "aira_speaking"
    PAUSED = "paused"
    ERROR = "error"

    @property
    def label(self) -> str:
        labels = {
            self.DISABLED: "Wake Word Disabled",
            self.INITIALIZING: "Initializing Engine...",
            self.LISTENING_LOCALLY: "Listening Locally for 'Hey AIRA'",
            self.WAKE_WORD_DETECTED: "Wake Word Detected!",
            self.CAPTURING_COMMAND: "Capturing Command...",
            self.RECOGNIZING_SPEECH: "Recognizing Spoken Speech...",
            self.WAITING_FOR_CONFIRMATION: "Waiting for User Approval...",
            self.PROCESSING_REQUEST: "Processing Request...",
            self.AIRA_SPEAKING: "AIRA Speaking...",
            self.PAUSED: "Wake Word Paused",
            self.ERROR: "Voice Service Error",
        }
        return labels.get(self, self.value)


@dataclass
class WakeWordEvent:
    state: WakeWordState
    timestamp: float
    detected_phrase: Optional[str] = None
    confidence: float = 0.0
    command_audio: Optional[bytes] = None
    error_message: Optional[str] = None


class WakeWordDetector:
    """Abstract base provider for wake-word detection."""

    def __init__(self, wake_phrase: str = "Hey AIRA"):
        self.wake_phrase = wake_phrase
        self._state: WakeWordState = WakeWordState.DISABLED

    @property
    def state(self) -> WakeWordState:
        return self._state

    def start(
        self,
        on_wake_detected: Optional[Callable[[str], None]] = None,
        on_command_captured: Optional[Callable[[bytes], None]] = None,
        on_state_change: Optional[Callable[[WakeWordState], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_state(self, new_state: WakeWordState) -> None:
        self._state = new_state


class LocalWakeWordDetector(WakeWordDetector):
    """Local, offline wake-word detector for macOS.

    - Continuously samples audio at 16kHz via sounddevice CoreAudio.
    - Uses local energy and acoustic spectral analysis for Voice Activity Detection (VAD).
    - Employs local keyword spotting for 'Hey AIRA' (and 'AIRA').
    - Zero ambient cloud transmission. All pre-activation audio is analyzed in local RAM buffers.
    - Transitions to command capture upon activation and terminates upon silence detection.
    """

    SAMPLE_RATE = 16000
    BLOCK_SIZE = 1280  # 80ms chunks
    ENERGY_THRESHOLD = 380.0  # RMS threshold for speech onset
    SILENCE_TIMEOUT_SEC = 1.1  # Speech end silence timeout
    MAX_COMMAND_SEC = 10.0  # Max command capture length

    def __init__(self, wake_phrase: str = "Hey AIRA", device_index: Optional[int] = None):
        super().__init__(wake_phrase=wake_phrase)
        self.device_index = device_index
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._stream_lock = threading.Lock()
        self._stream_closed = False
        self._whisper_model = None

        # Callbacks
        self._on_wake_detected = None
        self._on_command_captured = None
        self._on_state_change = None
        self._on_error = None

        # Audio buffers
        self._lock = threading.Lock()
        self._audio_queue: List[bytes] = []

    def _get_whisper_model(self):
        """Lazily initializes the persistent tiny Whisper model for local keyword spotting."""
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
                self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            except Exception as e:
                print(f"⚠️ [WakeWord] Could not load local whisper model: {e}")
        return self._whisper_model

    def set_state(self, new_state: WakeWordState) -> None:
        old_state = self._state
        self._state = new_state
        if old_state != new_state and self._on_state_change:
            try:
                self._on_state_change(new_state)
            except Exception as e:
                print(f"⚠️ [WakeWord] Error in state callback: {e}")

    def start(
        self,
        on_wake_detected: Optional[Callable[[str], None]] = None,
        on_command_captured: Optional[Callable[[bytes], None]] = None,
        on_state_change: Optional[Callable[[WakeWordState], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Starts continuous local wake-word listening on the default microphone."""
        if self._running:
            return True

        self._on_wake_detected = on_wake_detected
        self._on_command_captured = on_command_captured
        self._on_state_change = on_state_change
        self._on_error = on_error

        self.set_state(WakeWordState.INITIALIZING)

        try:
            import sounddevice as sd
            self._running = True
            self._stream_closed = False
            self._thread = threading.Thread(target=self._audio_loop, daemon=True, name="AiraWakeWordWorker")
            self._thread.start()
            return True
        except Exception as e:
            err_msg = f"Failed to initialize audio capture device: {str(e)}"
            self.set_state(WakeWordState.ERROR)
            if self._on_error:
                self._on_error(err_msg)
            return False

    def _close_stream_once(self) -> None:
        """Single-owner, thread-safe PortAudio stream termination to prevent double-free crashes."""
        with self._stream_lock:
            if self._stream is not None and not self._stream_closed:
                try:
                    self._stream.stop()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream_closed = True
                self._stream = None

    def stop(self) -> None:
        """Stops listening and safely releases audio hardware resources with strict single-owner cleanup."""
        # 1. Signal the worker loop to stop
        self._running = False

        # 2. Join the worker thread first so all PortAudio callbacks have completed
        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=2.0)
            self._thread = None

        # 3. Safely close PortAudio stream exactly once
        self._close_stream_once()

        # 4. Clear audio buffers
        with self._lock:
            self._audio_queue.clear()

        self.set_state(WakeWordState.DISABLED)

    def _audio_loop(self):
        """Dedicated thread reading microphone frames and running local wake detection."""
        import sounddevice as sd
        import numpy as np

        try:
            self.set_state(WakeWordState.LISTENING_LOCALLY)

            def audio_callback(indata, frames, time_info, status):
                if status and self._running:
                    pass  # CoreAudio overflow or underflow
                pcm_bytes = (indata * 32767).astype(np.int16).tobytes()
                with self._lock:
                    self._audio_queue.append(pcm_bytes)

            with self._stream_lock:
                self._stream = sd.InputStream(
                    samplerate=self.SAMPLE_RATE,
                    blocksize=self.BLOCK_SIZE,
                    device=self.device_index,
                    channels=1,
                    dtype="float32",
                    callback=audio_callback,
                )
                self._stream.start()

            # Buffer for keyword spotter window (~1.5 seconds = ~18 blocks)
            window_blocks: List[bytes] = []
            capturing_command = False
            command_blocks: List[bytes] = []
            last_speech_time = time.time()
            command_start_time = 0.0

            while self._running:
                chunk = None
                with self._lock:
                    if self._audio_queue:
                        chunk = self._audio_queue.pop(0)

                if chunk is None:
                    time.sleep(0.015)
                    continue

                # Compute RMS energy of this block
                shorts = struct.unpack(f"<{len(chunk)//2}h", chunk)
                rms = math.sqrt(sum(s * s for s in shorts) / max(1, len(shorts)))

                if not capturing_command:
                    # In LISTENING_LOCALLY mode
                    window_blocks.append(chunk)
                    if len(window_blocks) > 20:
                        window_blocks.pop(0)

                    # Only run detector if energy indicates vocal activity
                    if rms > self.ENERGY_THRESHOLD:
                        total_audio = b"".join(window_blocks)
                        detected, phrase = self._check_wake_phrase(total_audio)
                        if detected:
                            self.set_state(WakeWordState.WAKE_WORD_DETECTED)
                            if self._on_wake_detected:
                                self._on_wake_detected(phrase)

                            # Transition to command capture
                            time.sleep(0.15)  # brief cue pause
                            self.set_state(WakeWordState.CAPTURING_COMMAND)
                            capturing_command = True
                            command_blocks = []
                            command_start_time = time.time()
                            last_speech_time = time.time()
                            window_blocks.clear()
                else:
                    # In CAPTURING_COMMAND mode
                    command_blocks.append(chunk)
                    now = time.time()

                    if rms > self.ENERGY_THRESHOLD:
                        last_speech_time = now

                    # Check for speech-end silence or max timeout
                    silence_duration = now - last_speech_time
                    total_command_duration = now - command_start_time

                    if silence_duration >= self.SILENCE_TIMEOUT_SEC or total_command_duration >= self.MAX_COMMAND_SEC:
                        # Captured command utterance
                        capturing_command = False
                        full_command_audio = b"".join(command_blocks)

                        # At least 400ms (16kHz 16-bit mono = 32000 bytes/sec, 400ms = 12800 bytes)
                        if len(full_command_audio) > int(self.SAMPLE_RATE * 2 * 0.4):
                            from src.voice.providers import pcm_to_wav_bytes
                            wav_audio = pcm_to_wav_bytes(full_command_audio, sample_rate=self.SAMPLE_RATE)
                            self.set_state(WakeWordState.RECOGNIZING_SPEECH)
                            if self._on_command_captured:
                                self._on_command_captured(wav_audio)
                        else:
                            # Too short, resume listening
                            self.set_state(WakeWordState.LISTENING_LOCALLY)

                        command_blocks.clear()

        except Exception as e:
            print(f"⚠️ [WakeWord] Audio loop encountered error: {e}")
            self.set_state(WakeWordState.ERROR)
            if self._on_error:
                self._on_error(str(e))
        finally:
            self._close_stream_once()

    def _check_wake_phrase(self, pcm_bytes: bytes) -> (bool, str):
        """Local acoustic verification for 'Hey AIRA' or 'AIRA'.

        Uses persistent in-memory Whisper tiny on local CPU without disk I/O or container decoding.
        100% on-device, zero network transmission.
        """
        if not pcm_bytes or len(pcm_bytes) < 3200:
            return False, ""

        try:
            import numpy as np
            model = self._get_whisper_model()
            if model is None:
                return False, ""

            # Direct in-memory float32 normalization
            audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            segments, info = model.transcribe(
                audio_np,
                language="en",
                beam_size=1,
                vad_filter=False,
            )
            text = " ".join(seg.text for seg in segments).lower().strip()

            # Clean punctuation
            for ch in [".", ",", "!", "?", "'", '"', "-"]:
                text = text.replace(ch, "")

            wake_variants = ["hey aira", "aira", "hey ira", "ayra", "hey ayra", "hi aira", "hello aira"]
            for var in wake_variants:
                if var in text:
                    return True, var.title()
        except Exception as e:
            pass

        return False, ""
