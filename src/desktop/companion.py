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

import sys
import time
import signal
import threading
import asyncio
import requests
from typing import Optional, Dict, Any

from src.voice.wake_word import LocalWakeWordDetector, WakeWordState
from src.voice.providers import FasterWhisperSTTProvider, ElevenLabsTextToSpeechProvider, convert_audio_to_pcm_wav
from src.voice.interfaces import AudioChunk
from src.voice.service import get_voice_service
from src.desktop.service import get_desktop_service

BACKEND_API_URL = "http://localhost:8080"


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

    def _ms(self, start: float, end: float) -> str:
        if start <= 0 or end <= 0:
            return "n/a"
        return f"{round((end - start) * 1000, 1)}ms"

    def report(self):
        print(f"\n{'='*68}")
        print(f"📊 [Voice Latency Report] Request: {self.request_id}")
        print(f"{'='*68}")
        print(f"  T1→T3  Capture duration:              {self._ms(self.t1_wake_detected, self.t3_capture_end)}")
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
    """Local macOS companion process for system-wide hands-free AIRA interaction."""

    def __init__(self, backend_url: str = BACKEND_API_URL):
        self.backend_url = backend_url
        self.detector = LocalWakeWordDetector(wake_phrase="Hey AIRA")
        # Pre-create and warm the Whisper model at construction so the first
        # voice command does not pay model initialization latency (~2-4s on CPU).
        self.stt = FasterWhisperSTTProvider(model_size="tiny")
        self.tts = get_voice_service().tts
        self.desktop_service = get_desktop_service()
        self._shutdown_event = threading.Event()
        self._running = False
        # Per-request timing state (set per command in audio callback thread)
        self._current_timer: Optional[VoiceRequestTimer] = None
        self._wake_perf_t: float = 0.0   # perf_counter when wake word fires
        self._request_counter: int = 0

    def _warmup_whisper(self):
        """Pre-warms the Whisper model by triggering a silent dummy inference.

        Faster-Whisper loads GGML model files and JIT-compiles on first use.
        Pre-warming at startup reduces first-command latency by 2–4 seconds.
        """
        import io
        import wave
        import struct
        import numpy as np
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
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.stt.transcribe(dummy_chunk, language="en"))
            loop.close()
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            print(f"✅ [Companion] Faster-Whisper warmed in {elapsed}ms — first command will be fast.")
        except Exception as e:
            print(f"⚠️ [Companion] Whisper warm-up skipped: {e}")

    def print_banner(self):
        print("=" * 64)
        print("  🎙️  PROJECT AIRA — MACOS SYSTEM COMPANION")
        print("  Local Wake-Word: 'Hey AIRA' | Engine: On-Device Faster-Whisper")
        is_neural = isinstance(self.tts, ElevenLabsTextToSpeechProvider) and bool(self.tts.api_key)
        voice_desc = "ElevenLabs Neural (Sarah - Conversational)" if is_neural else "Samantha (macOS Native Fallback)"
        print(f"  Voice: {voice_desc} | Mode: Privacy Guarded")
        print("  Status: VISIBLE LISTENING ACTIVE — Press Ctrl+C to Stop")
        print("=" * 64)

    def on_state_change(self, state: WakeWordState):
        status_icons = {
            WakeWordState.LISTENING_LOCALLY: "👂 [Companion] Listening locally for 'Hey AIRA'...",
            WakeWordState.WAKE_WORD_DETECTED: "✨ [Companion] WAKE WORD DETECTED: 'Hey AIRA'!",
            WakeWordState.CAPTURING_COMMAND: "🔴 [Companion] Capturing spoken command...",
            WakeWordState.RECOGNIZING_SPEECH: "⚙️ [Companion] Transcribing command speech...",
            WakeWordState.PROCESSING_REQUEST: "🧠 [Companion] Sending to AIRA Orchestrator...",
            WakeWordState.AIRA_SPEAKING: "🗣️ [Companion] AIRA Speaking...",
            WakeWordState.WAITING_FOR_CONFIRMATION: "⚠️ [Companion] Action requires human confirmation!",
            WakeWordState.DISABLED: "⏹️ [Companion] Wake-word listening stopped.",
            WakeWordState.ERROR: "❌ [Companion] Voice hardware error.",
        }
        msg = status_icons.get(state, f"ℹ️ [Companion] State: {state.value}")
        print(f"\r{msg}", flush=True)

    def on_wake_detected(self, phrase: str):
        # T1: wake word confirmed
        self._wake_perf_t = time.perf_counter()
        self._request_counter += 1
        print(f"\n🔔 [Companion] Wake Phrase Detected: '{phrase}'")

    def on_command_captured(self, audio_bytes: bytes):
        """Transcribes captured command audio, forwards to AIRA backend, and speaks answer."""
        import uuid
        # T3: audio handed to companion (capture ended)
        t3_capture_end = time.perf_counter()
        request_id = f"vreq_{uuid.uuid4().hex[:8]}"
        timer = VoiceRequestTimer(request_id)
        timer.t1_wake_detected = self._wake_perf_t
        timer.t3_capture_end = t3_capture_end
        self._current_timer = timer

        print(f"\n📝 [Companion] Processing captured command utterance... [ID: {request_id}]")
        self.detector.set_state(WakeWordState.RECOGNIZING_SPEECH)

        # T4: STT begins
        chunk = AudioChunk(data=audio_bytes, sample_rate=16000, channels=1, format="wav")
        timer.t4_stt_start = time.perf_counter()

        loop = asyncio.new_event_loop()
        try:
            trans_result = loop.run_until_complete(self.stt.transcribe(chunk, language="en"))
        except Exception as e:
            print(f"⚠️ [Companion] Transcription error: {e}")
            self.detector.set_state(WakeWordState.LISTENING_LOCALLY)
            loop.close()
            return
        finally:
            loop.close()

        # T5: STT done
        timer.t5_stt_done = time.perf_counter()

        transcript = trans_result.text.strip()
        if not transcript:
            print("⚠️ [Companion] No clear speech detected.")
            self.detector.set_state(WakeWordState.LISTENING_LOCALLY)
            return

        stt_ms = round((timer.t5_stt_done - timer.t4_stt_start) * 1000, 1)
        print(f"🗣️ User Spoke: \"{transcript}\" [STT: {stt_ms}ms, confidence: {trans_result.confidence:.2f}]")
        self.detector.set_state(WakeWordState.PROCESSING_REQUEST)

        # T6: backend request starts
        timer.t6_backend_sent = time.perf_counter()
        try:
            resp = requests.post(
                f"{self.backend_url}/api/chat",
                json={"prompt": transcript, "privacy_mode": "standard"},
                timeout=30.0,
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
                    self.detector.set_state(WakeWordState.WAITING_FOR_CONFIRMATION)
                    desc = pending_plan.get("reason") or "a system modification"
                    spoken_msg = f"I propose to {desc}. No changes have been made yet. Please review and confirm in AIRA."
                    self.speak_text(spoken_msg, request_id=req_id, timer=timer)
                else:
                    self.detector.set_state(WakeWordState.AIRA_SPEAKING)
                    self.speak_text(answer_text, request_id=req_id, timer=timer)
            else:
                timer.t7_backend_received = time.perf_counter()
                print(f"⚠️ [Companion] Backend returned status {resp.status_code}")
                self.speak_text("I encountered an issue communicating with the AIRA backend.", timer=timer)
        except Exception as e:
            timer.t7_backend_received = time.perf_counter()
            print(f"⚠️ [Companion] Failed contacting AIRA backend at {self.backend_url}: {e}")
            self.speak_text("I cannot reach the AIRA server. Please ensure the backend is running.", timer=timer)

        # T12: full cycle complete
        timer.t12_request_complete = time.perf_counter()
        timer.report()

        # Return to listening
        self.detector.set_state(WakeWordState.LISTENING_LOCALLY)

    def speak_text(self, text: str, request_id: Optional[str] = None, timer: Optional[VoiceRequestTimer] = None):
        """Speaks text using streaming neural ElevenLabs TTS with transparent fallback and latency reporting."""
        from src.voice.service import clean_text_for_speech
        clean = clean_text_for_speech(text, max_spoken_chars=350)
        req_tag = f" [Response ID: {request_id}]" if request_id else ""
        print(f"🤖 AIRA{req_tag}: \"{clean}\"")

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
                            if self._shutdown_event.is_set():
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
                        if len(play_buf) > 0 and not self._shutdown_event.is_set():
                            play_buf.append(0)
                            out_stream.write(bytes(play_buf))

                    if timer:
                        timer.t11_last_audio_played = time.perf_counter()

                try:
                    running_loop = asyncio.get_running_loop()
                except RuntimeError:
                    running_loop = None

                if running_loop and running_loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(lambda: asyncio.run(_stream_audio())).result()
                else:
                    asyncio.run(_stream_audio())

                # Verify that neural playback actually completed
                if getattr(self.tts, "last_provider_used", "elevenlabs") != "macos_say_fallback" and total_bytes > 0:
                    playback_success = True
                    t_end = time.perf_counter()
                    model_id = getattr(self.tts, "model_id", "eleven_v4_turbo")
                    voice_id = getattr(self.tts, "voice_id", "EXAVITQu4vr4xnSDxMaL")

                    # Report detailed TTS timing from provider's own perf_counter probes
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
                    print(f"   Note: 'Total speak_text wall time' = connection + TTS generation + audio playback duration")
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

    def run(self):
        """Starts the companion lifecycle with clean, asynchronous-safe signal handling."""
        self.print_banner()
        # Pre-warm Whisper so first command is fast
        self._warmup_whisper()
        self._running = True
        self._shutdown_event.clear()

        def _signal_handler(sig, frame):
            # Only set the stop flag; do NOT do native PortAudio calls or sys.exit in signal handler!
            self._shutdown_event.set()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)

        started = self.detector.start(
            on_wake_detected=self.on_wake_detected,
            on_command_captured=self.on_command_captured,
            on_state_change=self.on_state_change,
        )

        if not started:
            print("❌ [Companion] Failed to start wake-word detector. Check microphone permissions.")
            return

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
        self.detector.stop()
        # Close any persistent ElevenLabs WebSocket connection cleanly
        if isinstance(self.tts, ElevenLabsTextToSpeechProvider) and self.tts._persistent_ws is not None:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.tts._persistent_ws.close())
                loop.close()
            except Exception:
                pass
            self.tts._persistent_ws = None
        print("✅ [Companion] Stopped cleanly.")


def main():
    companion = AiraDesktopCompanion()
    companion.run()


if __name__ == "__main__":
    main()
