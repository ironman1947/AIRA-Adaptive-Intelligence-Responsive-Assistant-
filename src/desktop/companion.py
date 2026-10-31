"""AIRA macOS Desktop Companion Service.

Runs independently of the web browser as a local background or terminal service.
Subject to macOS microphone permissions. Never hides its listening state.
Provides system-wide 'Hey AIRA' detection, command execution, spoken responses,
and mandatory approval safeguards.

End-to-end latency reporting (14 stages, perf_counter resolution):
  T1  — wake word detected
  T2  — capture start
  T3  — capture end / audio handed to STT
  T4  — STT started
  T5  — STT completed
  T6  — orchestration request sent to backend
  T7  — backend response received (includes model execution)
  T8  — TTS stream start (WebSocket or HTTP connection open)
  T9  — first TTS PCM chunk received
  T10 — first audio frame written to PortAudio
  T11 — final audio frame written to PortAudio
  T12 — full request cycle complete
"""

import os
import sys
import time
import signal
import threading
import asyncio
import re
import requests
from typing import Optional, Dict, Any, List

from src.voice.wake_word import LocalWakeWordDetector, WakeWordState
from src.voice.state_machine import ConversationState, ConversationStateMachine
from src.voice.turn_detector import TurnDetector, VADConfig
from src.voice.providers import (
    FasterWhisperSTTProvider,
    ElevenLabsTextToSpeechProvider,
    MacOSTextToSpeechProvider,
    convert_audio_to_pcm_wav,
)
from src.voice.interfaces import AudioChunk
from src.voice.service import get_voice_service
from src.voice.live_provider import GeminiLiveVoiceProvider
from src.desktop.service import get_desktop_service

BACKEND_API_URL = "http://localhost:8080"


def is_farewell_phrase(text: str) -> bool:
    """Detects explicit session-ending phrases."""
    # Strip apostrophes first so "that's" -> "thats"
    clean = re.sub(r"['’]", "", text).lower().strip()
    clean = re.sub(r"[^\w\s]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    exact_phrases = {
        "goodbye",
        "goodbye aira",
        "bye",
        "bye aira",
        "bye bye",
        "stop listening",
        "stop listening aira",
        "stop conversation",
        "end conversation",
        "end session",
        "quit",
        "exit",
        "thats all",
        "thats all aira",
        "thats all for now",
        "that will be all",
        "see you later",
        "see you later aira",
        "bye aira see you later",
        "goodbye see you later",
    }
    if clean in exact_phrases:
        return True
    patterns = [
        r"\b(goodbye|bye\s+bye|see\s+you\s+later|talk\s+to\s+you\s+later)\b",
        r"\b(stop\s+listening|stop\s+conversation|end\s+conversation|end\s+session)\b",
        r"\b(thats\s+all|that\s+will\s+be\s+all)\b",
        r"^bye\b",
    ]
    return any(re.search(p, clean) for p in patterns)


class VoiceRequestTimer:
    """Monotonic perf_counter timestamps for one voice request cycle.

    Timing labels:
      t1_wake_detected        — WakeWordDetector fires on_wake_detected callback
      t2_capture_start        — Command audio capture begins (set internally by audio loop)
      t3_capture_end          — Audio capture ends; WAV bytes handed to companion
      t4_stt_start            — FasterWhisper.transcribe() called
      t5_stt_done             — Transcription text returned
      t6_backend_sent         — HTTP POST to /api/chat initiated
      t7_backend_received     — HTTP response body fully parsed
      t8_tts_connect          — synthesize_stream() coroutine entered (ElevenLabs connect begins)
      t9_tts_first_chunk      — First PCM bytes yielded by provider
      t10_first_audio_played  — First aligned chunk written to PortAudio
      t11_last_audio_played   — Final audio byte flushed to PortAudio
      t12_request_complete    — Companion returns to LISTENING_LOCALLY
    """

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.t1_wake_detected: float = 0.0
        self.t2_capture_start: float = 0.0
        self.t3_capture_end: float = 0.0
        self.t4_stt_start: float = 0.0
        self.t5_stt_done: float = 0.0
        self.t6_backend_sent: float = 0.0
        self.t7_backend_received: float = 0.0
        self.t8_tts_connect: float = 0.0
        self.t9_tts_first_chunk: float = 0.0
        self.t10_first_audio_played: float = 0.0
        self.t11_last_audio_played: float = 0.0
        self.t12_request_complete: float = 0.0
        self.audio_diagnostics: Optional[Dict[str, Any]] = None
        self.sample_duration_sec: float = 0.0

    def _ms(self, start: float, end: float) -> str:
        if start <= 0 or end <= 0:
            return "n/a"
        return f"{round((end - start) * 1000, 1)}ms"

    def report(self):
        print(f"\n{'='*68}")
        print(f"📊 [Voice Telemetry & Latency Report] Request: {self.request_id}")
        print(f"{'='*68}")
        if self.audio_diagnostics:
            sr = self.audio_diagnostics.get("sample_rate", 16000)
            ch = self.audio_diagnostics.get("channels", 1)
            dur = self.audio_diagnostics.get("duration_sec", self.sample_duration_sec)
            samples = self.audio_diagnostics.get("sample_count", int(dur * sr))
            rms = self.audio_diagnostics.get("rms_energy", 0.0)
            clip = self.audio_diagnostics.get("clipping_count", 0)
            sil = self.audio_diagnostics.get("silence_ratio", 0.0)
            print(f"  Captured Audio:   {sr}Hz mono PCM, {dur:.2f}s ({samples} samples)")
            print(f"  Diagnostics:      RMS: {rms} | Clipping: {clip} | Silence ratio: {sil*100:.0f}%")
        elif self.sample_duration_sec > 0:
            print(f"  Captured Audio:   16000Hz mono PCM, {self.sample_duration_sec:.2f}s")
        print(f"  T1→T3  Capture duration (turn):       {self._ms(self.t1_wake_detected, self.t3_capture_end)}")
        print(f"  T4→T5  STT / Transcription:           {self._ms(self.t4_stt_start, self.t5_stt_done)}")
        print(f"  T5→T6  Pre-backend overhead:          {self._ms(self.t5_stt_done, self.t6_backend_sent)}")
        print(f"  T6→T7  Orchestration + model latency: {self._ms(self.t6_backend_sent, self.t7_backend_received)}")
        print(f"  T7→T8  TTS prep overhead:             {self._ms(self.t7_backend_received, self.t8_tts_connect)}")
        print(f"  T8→T9  TTS TTFB (conn+first chunk):   {self._ms(self.t8_tts_connect, self.t9_tts_first_chunk)}")
        print(f"  T9→T10 Buffer→PortAudio delay:        {self._ms(self.t9_tts_first_chunk, self.t10_first_audio_played)}")
        print(f"  T10→T11 Playback duration:            {self._ms(self.t10_first_audio_played, self.t11_last_audio_played)}")
        print(f"  T8→T11 Total TTS (generation+play):   {self._ms(self.t8_tts_connect, self.t11_last_audio_played)}")
        print(f"  ---")
        print(f"  T1→T10 Wake→first audible response:   {self._ms(self.t1_wake_detected, self.t10_first_audio_played)}")
        print(f"  T1→T12 Total end-to-end:              {self._ms(self.t1_wake_detected, self.t12_request_complete)}")
        print(f"{'='*68}\n")


class AiraDesktopCompanion:
    """Local macOS companion process for continuous, natural multi-turn voice interaction."""

    is_farewell_phrase = staticmethod(is_farewell_phrase)

    def __init__(self, backend_url: str = BACKEND_API_URL, mode: Optional[str] = None):
        self.backend_url = backend_url

        # Mode resolution: "live" (Gemini Live API) or "chained" (Faster-Whisper -> Orchestrator -> ElevenLabs)
        env_mode = os.getenv("AIRA_VOICE_MODE", "").strip().lower()
        requested_mode = (mode or env_mode or ("live" if GeminiLiveVoiceProvider.is_available() else "chained")).lower()

        # Controlled fallback: if live requested but GEMINI_API_KEY missing or SDK unavailable
        if requested_mode == "live" and not GeminiLiveVoiceProvider.is_available():
            print("⚠️ [Companion] Live mode requested but GEMINI_API_KEY is not configured.")
            print("⚠️ [Companion] Controlled fallback active: using chained mode (Faster-Whisper → Orchestrator → ElevenLabs).")
            self.mode = "chained"
        else:
            self.mode = requested_mode

        self.live_provider: Optional[GeminiLiveVoiceProvider] = None
        if self.mode == "live":
            self.live_provider = GeminiLiveVoiceProvider()

        self.detector = LocalWakeWordDetector(wake_phrase="Hey AIRA")
        # Pre-create and warm the Whisper model at construction so the first
        # voice command does not pay model initialization latency (~2-4s on CPU).
        self.stt = FasterWhisperSTTProvider(model_size="tiny")
        self.tts = get_voice_service().tts
        self.desktop_service = get_desktop_service()
        self._shutdown_event = threading.Event()
        self._interrupt_speaking_event = threading.Event()
        self._is_speaking = False
        self._running = False
        self.language = os.getenv("AIRA_VOICE_LANGUAGE", "en").strip()

        # Dedicated persistent async worker loop and thread (eliminates loop mismatch errors)
        self._async_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._run_async_worker,
            daemon=True,
            name="AiraAsyncAudioWorker",
        )
        self._async_thread.start()

        # Authoritative conversation state machine
        self.sm = ConversationStateMachine()
        self.sm.add_listener(self._on_sm_transition)

        # Per-request timing state (set per command in audio callback thread)
        self._current_timer: Optional[VoiceRequestTimer] = None
        self._wake_perf_t: float = 0.0          # perf_counter when wake word fires
        self._turn_start_perf_t: float = 0.0     # perf_counter when current turn speech began
        self._request_counter: int = 0

    @property
    def conversation_state(self) -> ConversationState:
        return self.sm.state

    @property
    def session_id(self) -> Optional[str]:
        return self.sm.session_id

    @property
    def turn_number(self) -> int:
        return self.sm.turn_number

    def _run_async_worker(self):
        """Dedicated background event loop thread for async speech and audio operations."""
        asyncio.set_event_loop(self._async_loop)
        self._async_loop.run_forever()

    def _run_async(self, coro, timeout: Optional[float] = None) -> Any:
        """Safely dispatches coroutines to the dedicated background event loop."""
        if not hasattr(self, "_async_loop") or not self._async_loop.is_running():
            return asyncio.run(coro)
        future = asyncio.run_coroutine_threadsafe(coro, self._async_loop)
        return future.result(timeout=timeout)

    def _warmup_whisper(self):
        """Pre-warms the Whisper model by triggering a silent dummy inference.

        Faster-Whisper loads GGML model files and JIT-compiles on first use.
        Pre-warming at startup reduces first-command latency by 2–4 seconds.
        """
        import io
        import wave
        import struct
        print("⚙️ [Companion] Pre-warming Faster-Whisper model (tiny)...")
        t0 = time.perf_counter()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            silence = struct.pack("<3200h", *([0] * 3200))  # 0.2s silence
            wf.writeframes(silence)
        dummy_chunk = AudioChunk(data=buf.getvalue(), sample_rate=16000, channels=1, format="wav")
        try:
            self._run_async(self.stt.transcribe(dummy_chunk, language="en"), timeout=10.0)
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            print(f"✅ [Companion] Faster-Whisper warmed in {elapsed}ms — first command will be fast.")
        except Exception as e:
            print(f"⚠️ [Companion] Whisper warm-up skipped: {e}")

    def print_banner(self):
        print("=" * 68)
        print("  🎙️  PROJECT AIRA — MACOS SYSTEM COMPANION (V2 LIVE & CONTINUOUS)")
        print(f"  Active Mode: {self.mode.upper()} ({'Gemini Live Bidirectional S2S' if self.mode == 'live' else 'Faster-Whisper → Orchestrator → ElevenLabs'})")
        print("  Wake-Word: 'Hey AIRA' (Standby) | Session: Natural continuous conversation")
        if self.mode == "live":
            voice = getattr(self.live_provider, "voice_name", "Aoede")
            model = getattr(self.live_provider, "model", "gemini-2.0-flash-exp")
            print(f"  Live Model: {model} | Live Voice: {voice} (24kHz low-latency)")
        else:
            is_neural = isinstance(self.tts, ElevenLabsTextToSpeechProvider) and bool(self.tts.api_key)
            voice_desc = "ElevenLabs Neural (Sarah - Conversational)" if is_neural else "Samantha (macOS Native Fallback)"
            print(f"  Voice: {voice_desc} | STT: Faster-Whisper (language={self.language})")
        print("  Barge-in: Interrupt anytime during speech | Say 'Goodbye, AIRA' to exit")
        print("=" * 68)

    def _on_sm_transition(self, from_state: ConversationState, to_state: ConversationState, context: Dict[str, Any]):
        """Synchronizes backward-compatible detector state and status icons."""
        state_map = {
            ConversationState.STANDBY: WakeWordState.LISTENING_LOCALLY,
            ConversationState.WAKE_DETECTED: WakeWordState.WAKE_WORD_DETECTED,
            ConversationState.ACTIVE_LISTENING: WakeWordState.LISTENING_LOCALLY,
            ConversationState.CAPTURING_UTTERANCE: WakeWordState.CAPTURING_COMMAND,
            ConversationState.TRANSCRIBING: WakeWordState.RECOGNIZING_SPEECH,
            ConversationState.PROCESSING: WakeWordState.PROCESSING_REQUEST,
            ConversationState.SPEAKING: WakeWordState.AIRA_SPEAKING,
            ConversationState.INTERRUPTED: WakeWordState.PAUSED,
            ConversationState.ENDING_SESSION: WakeWordState.LISTENING_LOCALLY,
            ConversationState.ERROR: WakeWordState.ERROR,
        }
        mapped = state_map.get(to_state, WakeWordState.LISTENING_LOCALLY)
        if hasattr(self.detector, "set_state"):
            self.detector.set_state(mapped)

    def on_state_change(self, state: WakeWordState):
        status_icons = {
            WakeWordState.LISTENING_LOCALLY: "👂 [Companion] Listening locally...",
            WakeWordState.WAKE_WORD_DETECTED: "✨ [Companion] WAKE WORD DETECTED: 'Hey AIRA'!",
            WakeWordState.CAPTURING_COMMAND: "🔴 [Companion] Capturing spoken utterance...",
            WakeWordState.RECOGNIZING_SPEECH: "⚙️ [Companion] Transcribing speech...",
            WakeWordState.PROCESSING_REQUEST: "🧠 [Companion] Sending to AIRA Orchestrator...",
            WakeWordState.AIRA_SPEAKING: "🗣️ [Companion] AIRA Speaking...",
            WakeWordState.WAITING_FOR_CONFIRMATION: "⚠️ [Companion] Action requires human confirmation!",
            WakeWordState.DISABLED: "⏹️ [Companion] Voice capture stopped.",
            WakeWordState.ERROR: "❌ [Companion] Voice hardware error.",
        }
        msg = status_icons.get(state, f"ℹ️ [Companion] State: {state.value}")
        print(f"\r{msg}", flush=True)

    def on_wake_detected(self, phrase: str):
        """Fires when local keyword spotter detects 'Hey AIRA' in standby mode."""
        self._wake_perf_t = time.perf_counter()
        self._turn_start_perf_t = self._wake_perf_t
        self._request_counter += 1
        print(f"\n🔔 [Companion] Wake Phrase Detected: '{phrase}'")

        # Activate continuous conversation mode
        self.sm.transition_to(ConversationState.WAKE_DETECTED, reason="wake_phrase_detected")
        self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="session_activated")
        self.detector.set_mode("conversation")

        if self.mode == "live" and self.live_provider:
            print("📡 [Companion] Initializing Gemini Live bidirectional audio session...")
            try:
                self._run_async(self.live_provider.connect(), timeout=10.0)
                self._run_async(
                    self.live_provider.start_listening(
                        on_barge_in=self._on_live_barge_in,
                        on_turn_complete=self._on_live_turn_complete,
                        on_text=self._on_live_text,
                    )
                )
                print("✨ [Companion] Gemini Live ready. Speak naturally!")
            except Exception as e:
                print(f"⚠️ [Companion] Live connection failed: {e}. Falling back to chained mode.")
                self.mode = "chained"

        # Check if user spoke a command immediately in the same breath
        trailing = getattr(self.detector, "_last_trailing_audio", None)
        if trailing and len(trailing) > 4800:
            print("🔴 [Companion] Continuing speech captured immediately following wake phrase...")
            self.detector.turn_detector.is_capturing = True
            self.detector.turn_detector.utterance_start_time = time.time()
            self.detector.turn_detector.last_speech_time = time.time()
            self.detector.turn_detector.utterance_frames = [trailing]
            self.sm.transition_to(ConversationState.CAPTURING_UTTERANCE, reason="trailing_command_capture")
        else:
            print("👂 [Companion] I'm listening. (Say 'Goodbye, AIRA' to exit session)")

    def _on_live_audio_frame(self, chunk: bytes):
        """Streams microphone frame to Gemini Live during active live mode."""
        if self.mode == "live" and self.sm.is_in_active_session and self.live_provider and self.live_provider.is_connected:
            if not self.live_provider.is_speaking:
                try:
                    self._run_async(self.live_provider.send_audio_chunk(chunk))
                except Exception:
                    pass

    def _on_live_barge_in(self):
        """Callback when Gemini Live detects user speech while assistant is speaking."""
        print("\n⚡ [Companion] Live barge-in detected! Halting assistant playback.")
        if self.sm.state == ConversationState.SPEAKING:
            self.sm.interrupt(reason="live_server_barge_in")
            self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="ready_for_user_speech")

    def _on_live_turn_complete(self):
        """Callback when Gemini Live model finishes speaking a turn."""
        if self.sm.state == ConversationState.SPEAKING:
            self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="live_turn_complete")
            print(f"\n🟢 [Companion] Gemini Live ready for next turn (Turn {self.sm.turn_number + 1})...")

    def _on_live_text(self, text: str):
        """Callback for live assistant text output."""
        if self.sm.state != ConversationState.SPEAKING:
            self.sm.transition_to(ConversationState.SPEAKING, reason="live_assistant_speaking")
        print(f"🗣️ AIRA (Live): {text}", end="", flush=True)

    def on_idle_timeout(self):
        """Fires when user remains silent in active conversation for idle_timeout_sec."""
        if self.sm.is_in_active_session:
            timeout_sec = getattr(self.detector.turn_detector.config, "idle_timeout_sec", 25.0)
            print(f"\n⏰ [Companion] Active session idle timeout ({timeout_sec:.0f}s) reached. Concluding conversation session.")
            self.sm.transition_to(ConversationState.ENDING_SESSION, reason="idle_timeout")
            self.sm.transition_to(ConversationState.STANDBY, reason="session_concluded")
            self.detector.set_mode("standby")
            print("👂 [Companion] Standby: Listening locally for 'Hey AIRA'...")

    def on_speech_started(self):
        """Fires when VAD detects speech onset during active continuous conversation."""
        self._turn_start_perf_t = time.perf_counter()
        if self.sm.state == ConversationState.ACTIVE_LISTENING:
            self.sm.transition_to(ConversationState.CAPTURING_UTTERANCE, reason="speech_onset")
            print(f"\n🔴 [Companion] Speech detected — recording turn {self.sm.turn_number}...", flush=True)

    def interrupt(self, reason: str = "user_barge_in"):
        """Immediately halts assistant audio playback and prepares for user speech."""
        print(f"\n⚡ [Companion] Interruption triggered ({reason})! Halting speech playback.")
        self._interrupt_speaking_event.set()
        self._is_speaking = False
        self.detector.is_speaking = False

        if self.live_provider and self.live_provider.is_connected:
            self.live_provider.interrupt()

        # Terminate any native macOS say processes
        try:
            MacOSTextToSpeechProvider.stop_all_speech()
        except Exception:
            pass

        # Discard stale persistent WebSocket chunks if needed
        if hasattr(self.tts, "_persistent_ws") and self.tts._persistent_ws is not None:
            try:
                self._run_async(self.tts._persistent_ws.close(), timeout=1.0)
            except Exception:
                pass
            self.tts._persistent_ws = None

        if self.sm.is_in_active_session:
            self.sm.interrupt(reason=reason)
            self.detector.clear_buffers()
            self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="interruption_ready_for_next_turn")
            print("🟢 [Companion] Ready for user's next message after interruption.")

    def stop_conversation(self):
        """Explicitly stops the active continuous conversation and returns to standby."""
        if self.live_provider and self.live_provider.is_connected:
            try:
                self._run_async(self.live_provider.disconnect(), timeout=2.0)
            except Exception:
                pass

        if self.sm.is_in_active_session:
            print("\n🛑 [Companion] Stopping active conversation session...")
            self.sm.transition_to(ConversationState.ENDING_SESSION, reason="user_stop_control")
            self.sm.transition_to(ConversationState.STANDBY, reason="standby_resumed")
            self.detector.set_mode("standby")
            print("👂 [Companion] Standby: Listening locally for 'Hey AIRA'...")

    def on_command_captured(self, audio_bytes: bytes):
        """Transcribes captured utterance, forwards to AIRA backend with session_id, and speaks answer."""
        import uuid
        t3_capture_end = time.perf_counter()
        request_id = f"vreq_{uuid.uuid4().hex[:8]}"
        timer = VoiceRequestTimer(request_id)

        sample_count = len(audio_bytes) // 2
        sample_duration = sample_count / 16000.0
        timer.sample_duration_sec = sample_duration

        # Monotonic timer origin strictly reset per turn (eliminates 39s session-leak bug)
        t_turn_start = self._turn_start_perf_t if self._turn_start_perf_t > 0 else (t3_capture_end - sample_duration)
        timer.t1_wake_detected = t_turn_start
        timer.t2_capture_start = t_turn_start
        timer.t3_capture_end = t3_capture_end
        self._turn_start_perf_t = 0.0
        self._current_timer = timer

        # Update state machine: if still in ACTIVE_LISTENING, transition through CAPTURING_UTTERANCE first
        if self.sm.state == ConversationState.ACTIVE_LISTENING:
            self.sm.transition_to(ConversationState.CAPTURING_UTTERANCE, reason="speech_onset")
        if self.sm.state == ConversationState.CAPTURING_UTTERANCE:
            self.sm.transition_to(ConversationState.TRANSCRIBING, reason="audio_captured")
        else:
            self.detector.set_state(WakeWordState.RECOGNIZING_SPEECH)

        print(f"\n📝 [Companion] Processing captured utterance... [ID: {request_id} | Turn: {self.sm.turn_number}]")

        # T4: STT begins
        chunk = AudioChunk(data=audio_bytes, sample_rate=16000, channels=1, format="wav")
        timer.t4_stt_start = time.perf_counter()

        try:
            trans_result = self._run_async(self.stt.transcribe(chunk, language=self.language), timeout=25.0)
        except Exception as e:
            print(f"⚠️ [Companion] Transcription error: {e}")
            if self.sm.is_in_active_session:
                self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="transcription_error_recovered")
                self.detector.clear_buffers()
            else:
                self.detector.set_state(WakeWordState.LISTENING_LOCALLY)
            return

        # T5: STT done
        timer.t5_stt_done = time.perf_counter()
        timer.audio_diagnostics = trans_result.diagnostics

        transcript = trans_result.text.strip()
        if not transcript:
            print("⚠️ [Companion] No clear speech detected.")
            if self.sm.is_in_active_session:
                self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="empty_speech_recovered")
                self.detector.clear_buffers()
            else:
                self.detector.set_state(WakeWordState.LISTENING_LOCALLY)
            return

        stt_ms = round((timer.t5_stt_done - timer.t4_stt_start) * 1000, 1)
        print(f"🗣️ User Spoke: \"{transcript}\" [STT: {stt_ms}ms, confidence: {trans_result.confidence:.2f}, lang: {trans_result.language}]")

        # Recognition Uncertainty Handling: if confidence < 0.40, prompt user to clarify instead of submitting garble
        if trans_result.confidence < 0.40:
            print(f"⚠️ [Companion] Recognition uncertainty: confidence {trans_result.confidence:.2f} < 0.40 for '{transcript}'.")
            clarification = "I didn't quite catch that. Could you please repeat that?"
            if self.sm.is_in_active_session:
                self.sm.transition_to(ConversationState.SPEAKING, reason="recognition_uncertainty_prompt")
            else:
                self.detector.set_state(WakeWordState.AIRA_SPEAKING)
            self.speak_text(clarification, request_id=request_id, timer=timer)
            if self.sm.is_in_active_session and not self._interrupt_speaking_event.is_set():
                self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="waiting_for_repeat")
                self.detector.turn_detector.reset_active_listening()
                print(f"\n🟢 [Companion] Listening for clarification (Turn {self.sm.turn_number})...")
            return

        # Check for Session-Ending phrase
        if is_farewell_phrase(transcript):
            print(f"👋 [Companion] Recognized farewell: '{transcript}'. Concluding conversation.")
            if self.sm.is_in_active_session:
                self.sm.transition_to(ConversationState.ENDING_SESSION, reason="user_farewell")
            parting_msg = "Goodbye, Om! Have a wonderful day."
            self.speak_text(parting_msg, request_id=request_id, timer=timer)
            if self.sm.is_in_active_session:
                self.sm.transition_to(ConversationState.STANDBY, reason="session_concluded")
            self.detector.set_mode("standby")
            print("👂 [Companion] Standby: Listening locally for 'Hey AIRA'...")
            return

        # Normal command: Transition to PROCESSING
        if self.sm.is_in_active_session:
            self.sm.transition_to(ConversationState.PROCESSING, reason="sending_to_backend")
        else:
            self.detector.set_state(WakeWordState.PROCESSING_REQUEST)

        # T6: backend request starts
        timer.t6_backend_sent = time.perf_counter()
        try:
            resp = requests.post(
                f"{self.backend_url}/api/chat",
                json={
                    "prompt": transcript,
                    "session_id": self.sm.session_id,
                    "privacy_mode": "standard",
                },
                timeout=35.0,
            )
            # T7: backend response received
            timer.t7_backend_received = time.perf_counter()

            if resp.status_code == 200:
                data = resp.json()
                req_id = data.get("request_id", request_id)
                answer_text = data.get("result", "")
                requires_approval = data.get("approval_required", False)
                pending_plan = data.get("pending_approval")

                backend_ms = round((timer.t7_backend_received - timer.t6_backend_sent) * 1000, 1)
                print(f"🧠 [Companion] Backend answered in {backend_ms}ms [req: {req_id}]")

                if requires_approval and pending_plan:
                    if self.sm.is_in_active_session:
                        self.sm.transition_to(ConversationState.SPEAKING, reason="action_requires_approval")
                    else:
                        self.detector.set_state(WakeWordState.WAITING_FOR_CONFIRMATION)
                    desc = pending_plan.get("reason") or "a system modification"
                    spoken_msg = f"I propose to {desc}. No changes have been made yet. Please review and confirm in AIRA."
                    self.speak_text(spoken_msg, request_id=req_id, timer=timer)
                    if self.sm.is_in_active_session and not self._interrupt_speaking_event.is_set():
                        self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="waiting_for_user_approval")
                        self.detector.turn_detector.reset_active_listening()
                else:
                    if self.sm.is_in_active_session:
                        self.sm.transition_to(ConversationState.SPEAKING, reason="assistant_speaking")
                    else:
                        self.detector.set_state(WakeWordState.AIRA_SPEAKING)
                    self.speak_text(answer_text, request_id=req_id, timer=timer)
                    if self.sm.is_in_active_session and not self._interrupt_speaking_event.is_set():
                        self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="turn_complete_listen_next")
                        self.detector.turn_detector.reset_active_listening()
                        print(f"\n🟢 [Companion] Listening for next turn (Turn {self.sm.turn_number + 1})... (Say 'Goodbye, AIRA' to exit)")
            else:
                timer.t7_backend_received = time.perf_counter()
                print(f"⚠️ [Companion] Backend returned status {resp.status_code}")
                self.speak_text("I encountered an issue communicating with the AIRA backend.", timer=timer)
                if self.sm.is_in_active_session:
                    self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="backend_error_recovered")
                    self.detector.turn_detector.reset_active_listening()
        except Exception as e:
            timer.t7_backend_received = time.perf_counter()
            print(f"⚠️ [Companion] Failed contacting AIRA backend at {self.backend_url}: {e}")
            self.speak_text("I cannot reach the AIRA server. Please ensure the backend is running.", timer=timer)
            if self.sm.is_in_active_session:
                self.sm.transition_to(ConversationState.ACTIVE_LISTENING, reason="backend_error_recovered")
                self.detector.turn_detector.reset_active_listening()

        # T12: full cycle complete
        timer.t12_request_complete = time.perf_counter()
        timer.report()

        if not self.sm.is_in_active_session:
            self.detector.set_state(WakeWordState.LISTENING_LOCALLY)

    def speak_text(self, text: str, request_id: Optional[str] = None, timer: Optional[VoiceRequestTimer] = None, **kwargs):
        """Speaks text using streaming neural ElevenLabs TTS with transparent fallback and latency reporting."""
        from src.voice.service import clean_text_for_speech
        clean = clean_text_for_speech(text, max_spoken_chars=350)
        req_tag = f" [Response ID: {request_id}]" if request_id else ""
        print(f"🤖 AIRA{req_tag}: \"{clean}\"")

        self._interrupt_speaking_event.clear()
        self._is_speaking = True
        self.detector.is_speaking = True

        try:
            # 1. Attempt streaming playback via ElevenLabs and sounddevice
            if hasattr(self.tts, "synthesize_stream") and getattr(self.tts, "api_key", None):
                playback_success = False
                error_reason = None
                total_bytes = 0
                t_speak_start = time.perf_counter()
                if timer:
                    timer.t8_tts_connect = t_speak_start

                try:
                    import sounddevice as sd
                    sample_size = 2  # channels (1) * bytes_per_sample (2 for int16)
                    play_buf = bytearray()

                    async def _stream_audio():
                        nonlocal total_bytes, play_buf
                        t_first_chunk_local: Optional[float] = None
                        t_first_played_local: Optional[float] = None

                        with sd.RawOutputStream(samplerate=16000, channels=1, dtype='int16') as out_stream:
                            async for pcm_chunk in self.tts.synthesize_stream(clean):
                                if self._shutdown_event.is_set() or self._interrupt_speaking_event.is_set():
                                    try:
                                        out_stream.abort()
                                    except Exception:
                                        pass
                                    break
                                if t_first_chunk_local is None and len(pcm_chunk) > 0:
                                    t_first_chunk_local = time.perf_counter()
                                    if timer:
                                        timer.t9_tts_first_chunk = t_first_chunk_local
                                total_bytes += len(pcm_chunk)
                                play_buf.extend(pcm_chunk)
                                aligned_len = len(play_buf) - (len(play_buf) % sample_size)
                                if aligned_len > 0:
                                    out_stream.write(bytes(play_buf[:aligned_len]))
                                    if t_first_played_local is None:
                                        t_first_played_local = time.perf_counter()
                                        if timer:
                                            timer.t10_first_audio_played = t_first_played_local
                                    play_buf = play_buf[aligned_len:]

                            # Flush remaining sample
                            if len(play_buf) > 0 and not self._shutdown_event.is_set() and not self._interrupt_speaking_event.is_set():
                                play_buf.append(0)
                                out_stream.write(bytes(play_buf))

                        if timer:
                            timer.t11_last_audio_played = time.perf_counter()

                    self._run_async(_stream_audio(), timeout=40.0)

                    # Check if interrupted
                    if self._interrupt_speaking_event.is_set():
                        print("⚡ [Companion] Speech playback cancelled by interruption.")
                        return

                    # Verify that neural playback actually completed
                    if getattr(self.tts, "last_provider_used", "elevenlabs") != "macos_say_fallback" and total_bytes > 0:
                        playback_success = True
                        t_end = time.perf_counter()
                        model_id = getattr(self.tts, "model_id", "eleven_v4_turbo")
                        voice_id = getattr(self.tts, "voice_id", "EXAVITQu4vr4xnSDxMaL")

                        tts_timing = getattr(self.tts, "last_tts_timing", {})
                        ws_reused = tts_timing.get("ws_reused", False)
                        ws_connect_ms = tts_timing.get("ws_connect_ms", "?")
                        ws_setup_ms = tts_timing.get("ws_setup_ms", "?")
                        provider_ttfb_ms = tts_timing.get("ttfb_ms", "?")
                        stream_total_ms = tts_timing.get("stream_total_ms", "?")
                        total_wall_ms = round((t_end - t_speak_start) * 1000, 1)

                        print(f"🔊 [Audio Playback Report]")
                        print(f"   Provider: ElevenLabs Neural | Model: {model_id} | Voice: {voice_id} (Sarah - Conversational)")
                        print(f"   WS Connection: {'REUSED (no handshake cost)' if ws_reused else f'NEW — TLS handshake: {ws_connect_ms}ms, setup: {ws_setup_ms}ms'}")
                        print(f"   TTS TTFB: {provider_ttfb_ms}ms | Stream gen: {stream_total_ms}ms | PCM decoded: {total_bytes} bytes")
                        print(f"   Playback: HARDWARE OK | Total speak_text wall time: {total_wall_ms}ms")
                        return
                    else:
                        error_reason = (
                            getattr(self.tts, "last_status", {}).get("fallback_reason")
                            or "Neural stream produced zero audio"
                        )
                except Exception as e:
                    error_reason = str(e)

                # If we reached here, ElevenLabs failed — report explicitly before fallback!
                model_id = getattr(self.tts, "model_id", "eleven_v4_turbo")
                print("=" * 64)
                print(f"⚠️ [Audio Playback Fallback Alert]")
                print(f"   Provider: ElevenLabs Neural (Model: {model_id})")
                print(f"   Status: GENERATION/PLAYBACK FAILED")
                print(f"   Failure Reason: {error_reason}")
                print(f"   Action: Invoking visible fallback: macOS Native (Samantha)")
                print(f"   Notice: Neural voice did NOT play. Fallback voice active.")
                print("=" * 64)

            # 2. Resilient Fallback to macOS say
            import subprocess
            t_fallback_start = time.perf_counter()
            if timer and timer.t8_tts_connect <= 0:
                timer.t8_tts_connect = t_fallback_start
            try:
                subprocess.run(["/usr/bin/say", "-v", "Samantha", "-r", "185", clean], timeout=25)
                if timer:
                    timer.t10_first_audio_played = t_fallback_start
                    timer.t11_last_audio_played = time.perf_counter()
            except Exception as e:
                print(f"⚠️ macOS speech playback error: {e}")
        finally:
            # Echo Grace Period: Allow 250ms for speaker reverberation in room to decay
            time.sleep(0.25)
            # Atomically drain audio queue to prevent AIRA hearing her own voice
            self.detector.clear_buffers()
            self._is_speaking = False
            self.detector.is_speaking = False

    def run(self):
        """Starts the companion lifecycle with continuous conversation turn-taking and signal handling."""
        self.print_banner()
        # Pre-warm Whisper so first command is fast
        self._warmup_whisper()
        self._running = True
        self._shutdown_event.clear()

        def _signal_handler(sig, frame):
            self._shutdown_event.set()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)

        started = self.detector.start(
            on_wake_detected=self.on_wake_detected,
            on_command_captured=self.on_command_captured,
            on_state_change=self.on_state_change,
            on_idle_timeout=self.on_idle_timeout,
            on_speech_started=self.on_speech_started,
            on_live_audio_frame=self._on_live_audio_frame,
        )

        if not started:
            print("❌ [Companion] Failed to start wake-word detector. Check microphone permissions.")
            return

        # Start terminal input listener for manual barge-in / stop control
        def _terminal_input_listener():
            while self._running and not self._shutdown_event.is_set():
                try:
                    import select
                    if sys.stdin in select.select([sys.stdin], [], [], 0.5)[0]:
                        line = sys.stdin.readline().strip().lower()
                        if line in ("stop", "interrupt", "pause", "wait", "hush", ""):
                            if self._is_speaking or self.sm.state == ConversationState.SPEAKING:
                                self.interrupt(reason="terminal_barge_in")
                            elif line in ("stop", "exit", "quit", "bye"):
                                self.stop_conversation()
                except Exception:
                    break

        if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            t_input = threading.Thread(target=_terminal_input_listener, daemon=True, name="AiraTerminalInput")
            t_input.start()

        try:
            while not self._shutdown_event.is_set():
                self._shutdown_event.wait(timeout=0.25)
        finally:
            print("\n🛑 [Companion] Interruption signal received. Releasing audio hardware...")
            self.stop()

    def stop(self):
        """Idempotent, thread-safe companion shutdown."""
        self._running = False
        self._shutdown_event.set()
        self._interrupt_speaking_event.set()
        self.detector.stop()

        if self.live_provider and self.live_provider.is_connected:
            try:
                self._run_async(self.live_provider.disconnect(), timeout=1.0)
            except Exception:
                pass

        if self.sm.is_in_active_session:
            self.sm.reset_to_standby(reason="shutdown")
        # Close any persistent ElevenLabs WebSocket connection cleanly
        if hasattr(self, "_async_loop") and self._async_loop.is_running():
            if isinstance(self.tts, ElevenLabsTextToSpeechProvider) and self.tts._persistent_ws is not None:
                try:
                    self._run_async(self.tts._persistent_ws.close(), timeout=1.0)
                except Exception:
                    pass
                self.tts._persistent_ws = None
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
            if hasattr(self, "_async_thread") and self._async_thread.is_alive():
                self._async_thread.join(timeout=1.0)
        print("✅ [Companion] Stopped cleanly.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AIRA macOS Desktop Companion")
    parser.add_argument(
        "--mode",
        choices=["live", "chained"],
        default=None,
        help="Voice interaction mode: 'live' (Gemini Live API) or 'chained' (Faster-Whisper+Orchestrator+ElevenLabs)",
    )
    parser.add_argument("--gemini-api-key", default=None, help="Gemini API Key for live mode")
    parser.add_argument("--backend-url", default=BACKEND_API_URL, help="FastAPI backend URL")
    args = parser.parse_args()

    if args.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = args.gemini_api_key

    companion = AiraDesktopCompanion(backend_url=args.backend_url, mode=args.mode)
    companion.run()


if __name__ == "__main__":
    main()
