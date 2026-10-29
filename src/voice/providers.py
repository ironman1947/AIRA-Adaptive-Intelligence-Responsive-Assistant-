"""Concrete Speech-to-Text (STT) and Text-to-Speech (TTS) Providers for AIRA.

Provides:
- GoogleSpeechRecognitionSTTProvider: Online multilingual STT (en, hi, mr, code-mixed)
- FasterWhisperSTTProvider: Local offline STT using faster-whisper on Apple Silicon
- MacOSTextToSpeechProvider: Fast native macOS speech synthesis via 'say' (Samantha, Lekha, Tara)
- FallbackTTSProvider: Pure Python fallback for testing or non-macOS environments
"""

import os
import ssl
import time
import json
import base64
import tempfile
import subprocess
import asyncio
import httpx
import websockets
from pathlib import Path
from typing import Optional, Dict, Any, List, AsyncGenerator

import certifi

# Shared TLS context using certifi's verified CA bundle.
# On macOS, Python 3.11 installed from python.org does NOT automatically trust
# the system keychain, so ssl.create_default_context() with no CA file fails
# against ElevenLabs (and other modern TLS hosts) with CERTIFICATE_VERIFY_FAILED.
# Using certifi.where() provides the same Mozilla CA bundle that browsers trust.
_CERTIFI_SSL_CTX: Optional[ssl.SSLContext] = None

def _get_certifi_ssl_ctx() -> ssl.SSLContext:
    """Returns a cached SSLContext backed by the certifi CA bundle."""
    global _CERTIFI_SSL_CTX
    if _CERTIFI_SSL_CTX is None:
        _CERTIFI_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    return _CERTIFI_SSL_CTX

from src.voice.interfaces import (
    AudioChunk,
    TranscriptionResult,
    SpeechToTextProvider,
    TextToSpeechProvider,
)

def validate_wav_pcm(wav_bytes: bytes, target_sample_rate: int = 16000) -> bool:
    """Validates that bytes represent a valid RIFF WAVE PCM stream with matching parameters."""
    if not wav_bytes or len(wav_bytes) < 44:
        return False
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return False
    try:
        import io
        import wave
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            return channels == 1 and sampwidth == 2 and framerate == target_sample_rate
    except Exception:
        return False


def pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Wraps raw 16-bit mono PCM bytes into a standard RIFF WAVE file."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def convert_audio_to_pcm_wav(audio_bytes: bytes, target_sample_rate: int = 16000) -> bytes:
    """Converts any audio container (WebM, Opus, Ogg, MP3, AAC, FLAC, WAV, raw PCM) to 16kHz 16-bit mono PCM WAV.

    Validates audio signatures, decodes containers via PyAV, or wraps raw PCM directly.
    Rejects empty or corrupted payloads with structured ValueError.
    """
    if not audio_bytes or len(audio_bytes) < 12:
        raise ValueError("Audio payload is empty or too short to contain valid audio data.")

    # 1. Fast-path: Already a valid 16kHz 16-bit mono RIFF WAV
    if validate_wav_pcm(audio_bytes, target_sample_rate=target_sample_rate):
        return audio_bytes

    # 2. Check if input is raw 16-bit PCM bytes without a container header
    known_magic = (b"RIFF", b"\x1aE\xdf\xa3", b"OggS", b"ID3", b"fLaC")
    is_known_container = any(audio_bytes.startswith(m) for m in known_magic)
    if not is_known_container and len(audio_bytes) > 8 and audio_bytes[4:8] in (b"ftyp", b"moov"):
        is_known_container = True

    if not is_known_container and len(audio_bytes) % 2 == 0:
        # Raw 16-bit PCM buffer: wrap into valid RIFF WAV
        wrapped = pcm_to_wav_bytes(audio_bytes, sample_rate=target_sample_rate)
        if validate_wav_pcm(wrapped, target_sample_rate=target_sample_rate):
            return wrapped

    # 3. Decode compressed containers (WebM, Opus, OGG, MP3, AAC, FLAC, multi-channel WAV) using PyAV
    import io
    import wave
    try:
        import av
        input_io = io.BytesIO(audio_bytes)
        output_io = io.BytesIO()

        with av.open(input_io) as container:
            audio_streams = [s for s in container.streams if s.type == "audio"]
            if not audio_streams:
                raise ValueError("No audio streams found in container.")

            stream = audio_streams[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=target_sample_rate)

            with wave.open(output_io, "wb") as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(target_sample_rate)

                frame_count = 0
                for frame in container.decode(stream):
                    for resampled_frame in resampler.resample(frame):
                        wav_out.writeframes(resampled_frame.to_ndarray().tobytes())
                        frame_count += 1

                if frame_count == 0:
                    raise ValueError("Decoded audio stream contains zero audio frames.")

        decoded_data = output_io.getvalue()
        if validate_wav_pcm(decoded_data, target_sample_rate=target_sample_rate):
            return decoded_data
        raise ValueError("Decoded audio failed WAV PCM validation.")
    except Exception as e:
        raise ValueError(f"Failed to decode audio container: {e}")

# ------------------------------------------------------------------------------
# Speech-to-Text Providers
# ------------------------------------------------------------------------------

class GoogleSpeechRecognitionSTTProvider(SpeechToTextProvider):
    """Multilingual Speech Recognition using Google Speech API via speech_recognition.

    Supports English (en-US, en-IN), Hindi (hi-IN), Marathi (mr-IN), and mixed speech.
    Automatically decodes incoming WebM/Opus/WAV containers into PCM WAV before recognition.
    """

    LANGUAGE_MAP = {
        "en": "en-US",
        "en-IN": "en-IN",
        "hi": "hi-IN",
        "mr": "mr-IN",
        "auto": "en-US",
    }

    def __init__(self, default_language: str = "en"):
        import speech_recognition as sr
        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.default_language = default_language

    async def transcribe(self, audio: AudioChunk, language: Optional[str] = None) -> TranscriptionResult:
        start_time = time.time()
        target_lang = self.LANGUAGE_MAP.get(language or self.default_language, "en-US")

        if not audio or not audio.data:
            return TranscriptionResult(text="", confidence=0.0, is_final=True, duration_ms=0.0)

        # Convert and validate incoming audio container to 16kHz mono PCM WAV
        pcm_wav_bytes = convert_audio_to_pcm_wav(audio.data, target_sample_rate=16000)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(pcm_wav_bytes)

        try:
            with self.sr.AudioFile(tmp_path) as source:
                audio_data = self.recognizer.record(source)

            # Recognize using Google API
            text = self.recognizer.recognize_google(audio_data, language=target_lang)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            return TranscriptionResult(
                text=text.strip(),
                confidence=0.92,
                is_final=True,
                language=target_lang[:2],
                duration_ms=duration_ms,
            )
        except self.sr.UnknownValueError:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            return TranscriptionResult(
                text="",
                confidence=0.0,
                is_final=True,
                language=target_lang[:2],
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            print(f"⚠️ [GoogleSTT] Transcription error: {e}")
            raise RuntimeError(f"Speech recognition service error: {str(e)}")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def is_ready(self) -> bool:
        return self.sr is not None

class FasterWhisperSTTProvider(SpeechToTextProvider):
    """Local, offline Speech Recognition using faster-whisper.

    Executes on Apple Silicon CPU/GPU with zero cloud telemetry.
    Decodes audio in-memory to float32 NumPy array with zero disk temporary file dependencies.
    """

    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def is_ready(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    async def transcribe(self, audio: AudioChunk, language: Optional[str] = None) -> TranscriptionResult:
        import io
        import wave
        import numpy as np

        start_time = time.time()
        if not audio or not audio.data:
            return TranscriptionResult(text="", confidence=0.0, is_final=True, duration_ms=0.0)

        # 1. Convert and validate audio into 16kHz mono PCM WAV
        pcm_wav_bytes = convert_audio_to_pcm_wav(audio.data, target_sample_rate=16000)

        # 2. Extract float32 audio array directly in-memory (no temporary disk file)
        with wave.open(io.BytesIO(pcm_wav_bytes), "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return TranscriptionResult(text="", confidence=0.0, is_final=True, duration_ms=0.0)
            raw_frames = wf.readframes(n_frames)
            audio_np = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0

        model = self._get_model()
        try:
            lang_param = None if (language in ("auto", None)) else language
            segments, info = model.transcribe(
                audio_np,
                language=lang_param,
                beam_size=1,        # beam_size=1 is fastest for short voice commands (greedy decode)
                vad_filter=False,   # VAD adds ~100ms per utterance; wake-word detector already handles silence
                word_timestamps=False,  # Skip word-level alignment for lower latency
                condition_on_previous_text=False,  # No context needed for command transcription
            )
            full_text = " ".join(seg.text for seg in segments).strip()
            detected_lang = info.language if hasattr(info, "language") else "en"
            duration_ms = round((time.time() - start_time) * 1000, 2)

            return TranscriptionResult(
                text=full_text,
                confidence=float(getattr(info, "language_probability", 0.9)),
                is_final=True,
                language=detected_lang,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            print(f"⚠️ [FasterWhisper] Local transcription error: {e}")
            raise RuntimeError(f"Local speech recognition error: {str(e)}")


# ------------------------------------------------------------------------------
# Text-to-Speech Providers
# ------------------------------------------------------------------------------

class MacOSTextToSpeechProvider(TextToSpeechProvider):
    """Native macOS speech synthesis via the `/usr/bin/say` subsystem.

    Supports feminine-presenting voices:
    - Samantha (US English female - Default conversational tone)
    - Ava (Enhanced US female if installed)
    - Lekha (Hindi / Marathi native female with Devanagari script awareness)
    - Tara (Indian English female)
    - Karen (Australian English female)
    - Victoria (US English female)
    Runs 100% offline, zero network latency, zero cloud audio leaks.
    Supports instant speech cancellation for user interruptions.
    """

    VOICE_DEFAULTS = {
        "en": "Samantha",
        "hi": "Lekha",
        "mr": "Lekha",  # Lekha produces natural Marathi pronunciation
        "in": "Tara",
    }

    _active_processes: set = set()

    def __init__(self, default_voice: str = "Samantha", rate: int = 185):
        self.default_voice = default_voice
        self.rate = rate  # 185 wpm provides conversational pacing
        self.say_path = "/usr/bin/say"

    @classmethod
    def stop_all_speech(cls):
        """Immediately stops all ongoing macOS speech processes for interruption."""
        for proc in list(cls._active_processes):
            try:
                proc.terminate()
            except Exception:
                pass
        cls._active_processes.clear()
        try:
            subprocess.run(["/usr/bin/killall", "say"], capture_output=True, timeout=2)
        except Exception:
            pass

    def select_voice_for_text(self, text: str, user_voice_choice: Optional[str] = None) -> str:
        """Picks the best voice based on user preference or script detection."""
        if user_voice_choice:
            return user_voice_choice

        # Detect Devanagari script (Hindi / Marathi)
        has_devanagari = any("\u0900" <= char <= "\u097F" for char in text)
        if has_devanagari:
            return "Lekha"

        return self.default_voice

    async def synthesize(self, text: str, voice_style: Optional[str] = None) -> AudioChunk:
        clean_text = text.strip()
        if not clean_text:
            return AudioChunk(data=b"", sample_rate=16000)

        voice = self.select_voice_for_text(clean_text, voice_style)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            cmd = [
                self.say_path,
                "-v", voice,
                "-r", str(self.rate),
                "-o", tmp_path,
                "--data-format=LEI16@16000",
                clean_text,
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._active_processes.add(proc)
            stdout, stderr = proc.communicate(timeout=20)
            self._active_processes.discard(proc)

            if proc.returncode != 0:
                raise RuntimeError(f"macOS say failed: {stderr.decode('utf-8', errors='ignore')}")

            with open(tmp_path, "rb") as f:
                wav_bytes = f.read()

            return AudioChunk(data=wav_bytes, sample_rate=16000, channels=1, format="wav")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class FallbackTTSProvider(TextToSpeechProvider):
    """Fallback TTS returning valid WAV silence or tone for non-macOS or test environments."""

    async def synthesize(self, text: str, voice_style: Optional[str] = None) -> AudioChunk:
        # Generates a minimal 0.2s 16kHz 16-bit mono WAV
        import io
        import wave
        import struct

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            # Write 1600 frames of silence
            data = struct.pack("<1600h", *([0] * 1600))
            wf.writeframes(data)

        return AudioChunk(data=buf.getvalue(), sample_rate=16000, channels=1, format="wav")


class ElevenLabsTextToSpeechProvider(TextToSpeechProvider):
    """High-fidelity neural streaming speech synthesis via ElevenLabs API.

    Features:
    - Text-to-Dialogue WebSocket protocol for Eleven v4 Turbo and v3 models.
    - Standard HTTP streaming TTS endpoint with sample-aligned buffer for v2 models.
    - Zero samplesize misalignment: guaranteed strict sample-boundary buffering (len % 2 == 0).
    - Conversational feminine-presenting voice (Default: Sarah / EXAVITQu4vr4xnSDxMaL).
    - Tuned conversational voice settings (stability: 0.45, similarity: 0.78, speaker boost).
    - In-memory 16kHz 16-bit mono PCM stream with zero disk I/O.
    - Visible fallback reporting with explicit error telemetry.
    """

    DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # Sarah (Conversational female)
    DEFAULT_MODEL_ID = "eleven_v4_turbo"
    MULTILINGUAL_MODEL_ID = "eleven_multilingual_v2"

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        fallback_provider: Optional[TextToSpeechProvider] = None,
    ):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", self.DEFAULT_VOICE_ID)
        self.model_id = model_id or os.getenv("ELEVENLABS_TTS_MODEL", self.DEFAULT_MODEL_ID)
        self.fallback_provider = fallback_provider or (
            MacOSTextToSpeechProvider() if os.path.exists("/usr/bin/say") else FallbackTTSProvider()
        )
        self._active_clients: List[httpx.AsyncClient] = []
        self._active_websockets: List[Any] = []
        self.last_provider_used: str = "elevenlabs"
        self.last_metrics: Dict[str, Any] = {}
        self.last_status: Dict[str, Any] = {
            "generation_status": "initialized",
            "decoding_status": "ready",
            "playback_status": "idle",
            "fallback_used": False,
        }
        # Persistent WebSocket session for low-latency repeated requests.
        # One session per voice ID — the Text-to-Dialogue protocol binds voices at connection time.
        self._persistent_ws: Optional[Any] = None
        self._persistent_ws_voice_id: Optional[str] = None
        self._persistent_ws_model_id: Optional[str] = None
        self.last_tts_timing: Dict[str, Any] = {}  # filled after each stream with per-stage perf_counter timings

    def stop_all_speech(self):
        """Cancels any active streaming requests and interrupts fallback engines."""
        for ws in list(self._active_websockets):
            try:
                asyncio.create_task(ws.close())
            except Exception:
                pass
        self._active_websockets.clear()

        for client in list(self._active_clients):
            try:
                asyncio.create_task(client.aclose())
            except Exception:
                pass
        self._active_clients.clear()

        if hasattr(self.fallback_provider, "stop_all_speech"):
            self.fallback_provider.stop_all_speech()

    def _select_model(self, text: str) -> str:
        """Selects the best ElevenLabs model based on text script (Devanagari -> multilingual)."""
        # eleven_v4_turbo inherently supports 94 languages including Hindi/Marathi
        if self.model_id.startswith("eleven_v4"):
            return self.model_id
        has_devanagari = any("\u0900" <= c <= "\u097F" for c in text)
        if has_devanagari:
            return self.MULTILINGUAL_MODEL_ID
        return self.model_id

    async def synthesize_stream(self, text: str, voice_style: Optional[str] = None) -> AsyncGenerator[bytes, None]:
        """Yields raw 16kHz 16-bit mono PCM chunks guaranteed to be sample-aligned (len % 2 == 0).

        Stage timing (perf_counter) is stored in self.last_metrics after streaming completes:
          ws_connect_ms    — TLS handshake + WebSocket open time (0 if connection reused)
          ws_setup_ms      — Voice registration round-trip
          ttfb_ms          — Time from text sent to first PCM chunk received
          stream_total_ms  — Total streaming duration until final audio chunk

        Uses:
        - Strategy A: Persistent Text-to-Dialogue WebSocket for eleven_v4_turbo / v3 models.
          One connection per voice session; TLS handshake is paid only once.
        - Strategy B: HTTP streaming TTS endpoint for v2 / fallback models.
        Buffers incomplete sample boundaries so sample-processing functions and
        sounddevice.RawOutputStream never encounter 'len(data) not divisible by samplesize'.
        """
        clean_text = text.strip()
        if not clean_text:
            return

        if not self.api_key:
            err_msg = "No ELEVENLABS_API_KEY configured."
            print(f"⚠️ [ElevenLabs TTS] {err_msg} Invoking visible fallback to macOS speech.")
            self.last_provider_used = "macos_say_fallback"
            self.last_status = {
                "generation_status": "failed",
                "decoding_status": "n/a",
                "playback_status": "fallback_invoked",
                "fallback_reason": err_msg,
                "fallback_used": True,
            }
            self.last_metrics = {
                "provider": "macos_say_fallback",
                "fallback_reason": err_msg,
            }
            chunk = await self.fallback_provider.synthesize(clean_text, voice_style=voice_style)
            if chunk.data and len(chunk.data) > 44:
                pcm_data = chunk.data[44:]
                aligned_len = len(pcm_data) - (len(pcm_data) % 2)
                if aligned_len > 0:
                    yield pcm_data[:aligned_len]
            return

        voice_id = voice_style if (voice_style and voice_style != "Samantha") else self.voice_id
        model_id = self._select_model(clean_text)

        # Buffer for sample boundary alignment (16-bit mono PCM = 2 bytes per sample)
        sample_buffer = bytearray()
        sample_size = 2

        # Timing probes (perf_counter, sub-millisecond resolution)
        t_ws_connect_start: float = 0.0
        t_ws_ready: float = 0.0
        t_setup_sent: float = 0.0
        t_setup_done: float = 0.0
        t_text_sent: float = 0.0
        t_first_chunk: Optional[float] = None

        # ----------------------------------------------------------------------
        # Strategy A: Persistent Text-to-Dialogue WebSocket (eleven_v4_turbo / v3)
        # A new WebSocket connection pays ~200-500ms TLS handshake cost per utterance.
        # By reusing one authenticated connection across conversational turns the
        # handshake is paid only once for the session lifetime.
        # ----------------------------------------------------------------------
        if model_id.startswith("eleven_v4") or model_id.startswith("eleven_v3"):
            ws_url = (
                f"wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
                f"?output_format=pcm_16000&model_id={model_id}"
            )
            headers = {"xi-api-key": self.api_key}
            ws_reused = False

            try:
                # --- Attempt to reuse an existing open connection ---
                existing = self._persistent_ws
                if (
                    existing is not None
                    and getattr(existing, "state", None) is not None
                    and existing.state.value < 3  # websockets states: OPEN=1, CLOSING=2, CLOSED=3
                    and self._persistent_ws_voice_id == voice_id
                    and self._persistent_ws_model_id == model_id
                ):
                    ws_reused = True
                    ws = existing
                else:
                    # Close any stale connection cleanly before opening a new one
                    if self._persistent_ws is not None:
                        try:
                            await self._persistent_ws.close()
                        except Exception:
                            pass
                        self._persistent_ws = None

                    t_ws_connect_start = time.perf_counter()
                    ws = await websockets.connect(
                        ws_url,
                        additional_headers=headers,
                        ssl=_get_certifi_ssl_ctx(),
                        open_timeout=8.0,
                        ping_interval=20,
                        ping_timeout=10,
                    )
                    t_ws_ready = time.perf_counter()
                    self._persistent_ws = ws
                    self._persistent_ws_voice_id = voice_id
                    self._persistent_ws_model_id = model_id
                    self._active_websockets.append(ws)

                    # Voice registration — send once per new connection
                    t_setup_sent = time.perf_counter()
                    setup_msg = {
                        "voices": [voice_id],
                        "xi_api_key": self.api_key,
                        "voice_settings": {
                            "stability": 0.45,
                            "similarity_boost": 0.78,
                            "style": 0.05,
                            "use_speaker_boost": True,
                        }
                    }
                    await ws.send(json.dumps(setup_msg))
                    t_setup_done = time.perf_counter()

                # Send the dialogue turn + flush signal
                t_text_sent = time.perf_counter()
                input_msg = {
                    "inputs": [{
                        "text": clean_text,
                        "voice_id": voice_id,
                        "new_turn": True
                    }]
                }
                await ws.send(json.dumps(input_msg))
                await ws.send(json.dumps({"flush": True}))

                # Stream audio chunks with sample boundary buffering
                async for raw in ws:
                    msg = json.loads(raw)
                    if "audio" in msg and msg["audio"]:
                        raw_pcm = base64.b64decode(msg["audio"])
                        if raw_pcm:
                            if t_first_chunk is None:
                                t_first_chunk = time.perf_counter()
                            sample_buffer.extend(raw_pcm)
                            aligned_len = len(sample_buffer) - (len(sample_buffer) % sample_size)
                            if aligned_len > 0:
                                yield bytes(sample_buffer[:aligned_len])
                                sample_buffer = sample_buffer[aligned_len:]
                    if msg.get("is_final_audio_for_turn"):
                        break

                # Flush remaining sample-aligned bytes
                if len(sample_buffer) > 0:
                    sample_buffer.append(0)
                    yield bytes(sample_buffer)

                t_stream_done = time.perf_counter()
                self.last_provider_used = "elevenlabs"

                # Record per-stage timing in last_metrics for the companion to report
                ws_connect_ms = round((t_ws_ready - t_ws_connect_start) * 1000, 1) if not ws_reused else 0.0
                ws_setup_ms = round((t_setup_done - t_setup_sent) * 1000, 1) if not ws_reused else 0.0
                ttfb_ms = round(((t_first_chunk or t_stream_done) - t_text_sent) * 1000, 1)
                stream_total_ms = round((t_stream_done - (t_ws_connect_start or t_text_sent)) * 1000, 1)
                self.last_tts_timing = {
                    "ws_reused": ws_reused,
                    "ws_connect_ms": ws_connect_ms,
                    "ws_setup_ms": ws_setup_ms,
                    "ttfb_ms": ttfb_ms,
                    "stream_total_ms": stream_total_ms,
                }
                return

            except Exception as ws_err:
                # Discard the stale persistent connection so next call reconnects clean
                if self._persistent_ws is not None:
                    try:
                        await self._persistent_ws.close()
                    except Exception:
                        pass
                    self._persistent_ws = None
                    self._persistent_ws_voice_id = None
                    self._persistent_ws_model_id = None
                if ws_err is not None:
                    try:
                        if ws in self._active_websockets:
                            self._active_websockets.remove(ws)
                    except Exception:
                        pass
                print(f"⚠️ [ElevenLabs TTD WebSocket] WebSocket error ({ws_err}); attempting HTTP stream fallback...")

        # ----------------------------------------------------------------------
        # Strategy B: HTTP Streaming TTS endpoint (for turbo_v2_5, multilingual, or WS fallback)
        # ----------------------------------------------------------------------
        http_model = model_id if not model_id.startswith("eleven_v4") else "eleven_turbo_v2_5"
        http_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format=pcm_16000"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": clean_text,
            "model_id": http_model,
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.78,
                "style": 0.05,
                "use_speaker_boost": True,
            }
        }

        t_http_start = time.perf_counter()
        t_first_chunk_http: Optional[float] = None
        try:
            async with httpx.AsyncClient(timeout=20.0, verify=certifi.where()) as client:
                self._active_clients.append(client)
                try:
                    async with client.stream("POST", http_url, headers=headers, json=payload) as resp:
                        if resp.status_code != 200:
                            err_body = await resp.aread()
                            raise RuntimeError(f"ElevenLabs HTTP API error {resp.status_code}: {err_body.decode('utf-8', errors='ignore')}")

                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                if t_first_chunk_http is None:
                                    t_first_chunk_http = time.perf_counter()
                                sample_buffer.extend(chunk)
                                aligned_len = len(sample_buffer) - (len(sample_buffer) % sample_size)
                                if aligned_len > 0:
                                    yield bytes(sample_buffer[:aligned_len])
                                    sample_buffer = sample_buffer[aligned_len:]

                    if len(sample_buffer) > 0:
                        sample_buffer.append(0)
                        yield bytes(sample_buffer)

                    t_http_done = time.perf_counter()
                    self.last_provider_used = "elevenlabs"
                    ttfb_ms = round(((t_first_chunk_http or t_http_done) - t_http_start) * 1000, 1)
                    self.last_tts_timing = {
                        "ws_reused": False,
                        "ws_connect_ms": 0.0,
                        "ws_setup_ms": 0.0,
                        "ttfb_ms": ttfb_ms,
                        "stream_total_ms": round((t_http_done - t_http_start) * 1000, 1),
                        "http_model": http_model,
                    }
                    return
                finally:
                    if client in self._active_clients:
                        self._active_clients.remove(client)

        except Exception as http_err:
            print(f"⚠️ [ElevenLabs TTS] Streaming failed ({http_err}); invoking visible fallback to macOS speech.")
            self.last_provider_used = "macos_say_fallback"
            self.last_status = {
                "generation_status": "failed",
                "decoding_status": "n/a",
                "playback_status": "fallback_invoked",
                "fallback_reason": str(http_err),
                "fallback_used": True,
            }
            self.last_metrics = {
                "provider": "macos_say_fallback",
                "fallback_reason": str(http_err),
            }
            chunk = await self.fallback_provider.synthesize(clean_text, voice_style=voice_style)
            if chunk.data and len(chunk.data) > 44:
                pcm_data = chunk.data[44:]
                aligned_len = len(pcm_data) - (len(pcm_data) % 2)
                if aligned_len > 0:
                    yield pcm_data[:aligned_len]

    async def synthesize(self, text: str, voice_style: Optional[str] = None) -> AudioChunk:
        """Synthesizes text to a complete 16kHz mono WAV AudioChunk using ElevenLabs."""
        clean_text = text.strip()
        if not clean_text:
            return AudioChunk(data=b"", sample_rate=16000)

        start_time = time.time()
        pcm_chunks = []
        ttfb = None

        try:
            async for chunk in self.synthesize_stream(clean_text, voice_style=voice_style):
                if ttfb is None and len(chunk) > 0:
                    ttfb = time.time() - start_time
                pcm_chunks.append(chunk)

            total_pcm = b"".join(pcm_chunks)
            if not total_pcm:
                raise RuntimeError("ElevenLabs streaming produced 0 bytes of audio data")

            duration = time.time() - start_time
            ttfb_ms = round((ttfb or duration) * 1000, 1)
            duration_ms = round(duration * 1000, 1)

            if self.last_provider_used == "elevenlabs":
                voice_id = voice_style if (voice_style and voice_style != "Samantha") else self.voice_id
                model_id = self._select_model(clean_text)
                endpoint = (
                    "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
                    if (model_id.startswith("eleven_v4") or model_id.startswith("eleven_v3"))
                    else f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
                )
                self.last_metrics = {
                    "provider": "elevenlabs",
                    "voice_id": voice_id,
                    "voice_label": "Sarah - Conversational",
                    "model_id": model_id,
                    "endpoint": endpoint,
                    "ttfb_ms": ttfb_ms,
                    "duration_ms": duration_ms,
                    "bytes": len(total_pcm),
                    "sample_rate": 16000,
                    "channels": 1,
                    "encoding": "pcm_s16le",
                }
                self.last_status = {
                    "generation_status": "success",
                    "decoding_status": "valid_pcm16",
                    "playback_status": "ready",
                    "fallback_used": False,
                }
                print(f"🔊 [ElevenLabs TTS] Synthesized {len(total_pcm)} bytes in {duration_ms}ms (TTFB: {ttfb_ms}ms, voice: {voice_id}, model: {model_id})")
            else:
                self.last_metrics.setdefault("provider", self.last_provider_used)
                self.last_metrics.setdefault("fallback_reason", self.last_status.get("fallback_reason", "Fallback invoked"))
                self.last_metrics.setdefault("duration_ms", duration_ms)
                self.last_metrics.setdefault("bytes", len(total_pcm))

            wav_data = pcm_to_wav_bytes(total_pcm, sample_rate=16000)
            return AudioChunk(data=wav_data, sample_rate=16000, channels=1, format="wav")

        except Exception as e:
            print(f"⚠️ [ElevenLabs TTS] Neural synthesis failed ({e}); falling back to local speech engine with alert.")
            self.last_provider_used = "macos_say_fallback"
            self.last_status = {
                "generation_status": "failed",
                "decoding_status": "n/a",
                "playback_status": "fallback_invoked",
                "fallback_reason": str(e),
                "fallback_used": True,
            }
            self.last_metrics = {
                "provider": "macos_say_fallback",
                "fallback_reason": str(e),
            }
            return await self.fallback_provider.synthesize(clean_text, voice_style=voice_style)


def get_available_macos_voices() -> List[Dict[str, str]]:
    """Returns available macOS system voices or curated defaults."""
    default_voices = [
        {"id": "Samantha", "name": "Samantha (US Female - Default)", "language": "en-US", "gender": "female"},
        {"id": "Lekha", "name": "Lekha (Hindi / Marathi Native)", "language": "hi-IN", "gender": "female"},
        {"id": "Tara", "name": "Tara (Indian English)", "language": "en-IN", "gender": "female"},
        {"id": "Aman", "name": "Aman (Indian English)", "language": "en-IN", "gender": "male"},
        {"id": "Karen", "name": "Karen (Australian English)", "language": "en-AU", "gender": "female"},
        {"id": "Victoria", "name": "Victoria (US Female)", "language": "en-US", "gender": "female"},
        {"id": "Daniel", "name": "Daniel (UK Male)", "language": "en-GB", "gender": "male"},
    ]
    if not os.path.exists("/usr/bin/say"):
        return default_voices

    try:
        proc = subprocess.run(["/usr/bin/say", "-v", "?"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            system_names = {line.split()[0].strip() for line in proc.stdout.strip().splitlines() if line.strip()}
            available = [v for v in default_voices if v["id"] in system_names]
            if available:
                return available
    except Exception:
        pass
    return default_voices
