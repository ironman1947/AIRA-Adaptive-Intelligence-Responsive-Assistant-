"""AIRA Gemini Live Voice Provider.

Implements native, real-time, bidirectional streaming speech-to-speech interaction
using the official Google GenAI Live API SDK (`google.genai`).

Audio Specifications:
- Input: 16 kHz, 16-bit, Little-Endian, Mono PCM (`audio/pcm;rate=16000`)
- Output: 24 kHz, 16-bit, Little-Endian, Mono PCM (`audio/pcm;rate=24000`)
- Low Latency: Sub-500ms time-to-first-byte streamed directly to PortAudio
- Server-side VAD & Interruption Handling: Immediate cancellation on barge-in
- Function Calling: Integration with AIRA desktop tools and system utilities
"""

import os
import sys
import time
import asyncio
import threading
from typing import Optional, Dict, Any, Callable, List, AsyncGenerator
from zoneinfo import ZoneInfo
from datetime import datetime

import sounddevice as sd

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    types = None
    genai = None

from src.desktop.service import get_desktop_service


class GeminiLiveAudioPlayer:
    """Thread-safe 24kHz raw PCM audio output stream for Gemini Live responses."""

    def __init__(self, sample_rate: int = 24000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream: Optional[sd.RawOutputStream] = None
        self._lock = threading.Lock()
        self._is_playing = False

    def start(self):
        with self._lock:
            if self._stream is None or not self._stream.active:
                try:
                    self._stream = sd.RawOutputStream(
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        dtype="int16",
                        blocksize=1024,
                    )
                    self._stream.start()
                    self._is_playing = True
                except Exception as e:
                    print(f"⚠️ [LiveAudioPlayer] Failed starting audio output stream: {e}")

    def write(self, pcm_bytes: bytes):
        """Immediately writes audio frames to the active output stream."""
        if not pcm_bytes:
            return
        # Ensure sample boundary alignment (2 bytes per sample for int16 mono)
        aligned_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
        if aligned_len <= 0:
            return
        data = pcm_bytes[:aligned_len]

        with self._lock:
            if self._stream is None or not self._stream.active:
                self.start()
            if self._stream and self._stream.active:
                try:
                    self._stream.write(data)
                except Exception as e:
                    print(f"⚠️ [LiveAudioPlayer] Write error: {e}")

    def abort(self):
        """Immediately interrupts playback and drains any queued buffers (barge-in)."""
        with self._lock:
            if self._stream:
                try:
                    self._stream.abort()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._is_playing = False

    def stop(self):
        """Stops the stream cleanly."""
        with self._lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._is_playing = False


class GeminiLiveVoiceProvider:
    """Modular client for Gemini Live bidirectional voice streaming."""

    DEFAULT_MODEL = "gemini-2.0-flash-exp"
    DEFAULT_VOICE = "Aoede"  # Conversational feminine-presenting voice

    AIRA_SYSTEM_INSTRUCTION = (
        "You are AIRA, a highly capable, natural, and low-latency voice assistant for macOS. "
        "You speak with a warm, conversational, concise tone. "
        "Always give direct, natural spoken answers without markdown symbols, code blocks, or bullet lists. "
        "You have direct access to desktop utilities and macOS controls. "
        "For system time queries, answer using Asia/Kolkata (IST). "
        "If the user asks to open an application or perform a system change, call the appropriate tool."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        voice_name: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self.model = model or os.getenv("GEMINI_LIVE_MODEL", self.DEFAULT_MODEL)
        self.voice_name = voice_name or os.getenv("GEMINI_LIVE_VOICE", self.DEFAULT_VOICE)
        self.system_instruction = system_instruction or self.AIRA_SYSTEM_INSTRUCTION

        self.player = GeminiLiveAudioPlayer(sample_rate=24000, channels=1)
        self.client: Optional[Any] = None
        self.session: Optional[Any] = None
        self._session_ctx: Optional[Any] = None

        self._is_connected = False
        self._is_speaking = False
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None

        # Callbacks
        self.on_barge_in: Optional[Callable[[], None]] = None
        self.on_turn_complete: Optional[Callable[[], None]] = None
        self.on_text_received: Optional[Callable[[str], None]] = None
        self.on_speech_started: Optional[Callable[[], None]] = None

        # Metrics
        self.last_ttfb_ms: float = 0.0
        self._last_speech_sent_time: float = 0.0

    @classmethod
    def is_available(cls) -> bool:
        """Checks if the google-genai SDK is installed and an API key is present."""
        if not GENAI_AVAILABLE:
            return False
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        return bool(key and key != "none" and len(key) > 5)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def _get_tools(self) -> List[Any]:
        """Defines AIRA function declarations for Gemini Live."""
        if not GENAI_AVAILABLE:
            return []

        return [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_current_time",
                        description="Returns the current accurate system time in IST (Asia/Kolkata).",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                    ),
                    types.FunctionDeclaration(
                        name="get_current_date",
                        description="Returns the current accurate system date in IST (Asia/Kolkata).",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                    ),
                    types.FunctionDeclaration(
                        name="desktop_open_application",
                        description="Opens or launches an authorized macOS desktop application (e.g. Safari, Terminal, Notes).",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "app_name": types.Schema(
                                    type=types.Type.STRING,
                                    description="Name of the application to launch",
                                )
                            },
                            required=["app_name"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="desktop_system_diagnostics",
                        description="Returns current macOS system metrics including CPU load, memory usage, and battery status.",
                        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
                    ),
                ]
            )
        ]

    async def connect(self):
        """Establishes a live bidirectional session with the Gemini Live API."""
        if not GENAI_AVAILABLE:
            raise RuntimeError("The google-genai SDK is not installed. Install via `uv pip install google-genai`.")

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        self.client = genai.Client(api_key=self.api_key)

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=self.system_instruction)]
            ),
            tools=self._get_tools(),
        )

        print(f"📡 [GeminiLive] Connecting to Live API (Model: {self.model}, Voice: {self.voice_name})...")
        self._session_ctx = self.client.aio.live.connect(model=self.model, config=config)
        self.session = await self._session_ctx.__aenter__()
        self._is_connected = True
        self._running = True
        self.player.start()
        print("✅ [GeminiLive] Live session established successfully.")

    async def send_audio_chunk(self, pcm_16k_bytes: bytes):
        """Streams a 16kHz 16-bit mono PCM chunk to Gemini Live."""
        if not self._is_connected or not self.session:
            return

        if self._last_speech_sent_time == 0.0:
            self._last_speech_sent_time = time.perf_counter()

        blob = types.Blob(
            data=pcm_16k_bytes,
            mime_type="audio/pcm;rate=16000",
        )
        await self.session.send_realtime_input(audio=blob)

    async def start_listening(
        self,
        on_barge_in: Optional[Callable[[], None]] = None,
        on_turn_complete: Optional[Callable[[], None]] = None,
        on_text: Optional[Callable[[str], None]] = None,
    ):
        """Starts the background listening task for processing server responses."""
        if on_barge_in:
            self.on_barge_in = on_barge_in
        if on_turn_complete:
            self.on_turn_complete = on_turn_complete
        if on_text:
            self.on_text_received = on_text

        self._listen_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self):
        """Processes real-time server messages (audio streaming, barge-in, tools)."""
        first_audio_received = False
        try:
            async for message in self.session.receive():
                if not self._running:
                    break

                # 1. Server Content (Audio / Text / Interruption)
                server_content = getattr(message, "server_content", None)
                if server_content:
                    # Check for Server-Side Interruption (Barge-In)
                    if getattr(server_content, "interrupted", False):
                        print("⚡ [GeminiLive] User barge-in detected! Aborting playback.")
                        self.player.abort()
                        self._is_speaking = False
                        first_audio_received = False
                        if self.on_barge_in:
                            self.on_barge_in()
                        continue

                    # Process Model Turn (Audio and Text)
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn:
                        for part in getattr(model_turn, "parts", []):
                            # Audio chunk (24kHz PCM)
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and getattr(inline_data, "data", None):
                                if not first_audio_received:
                                    first_audio_received = True
                                    if self._last_speech_sent_time > 0:
                                        self.last_ttfb_ms = round(
                                            (time.perf_counter() - self._last_speech_sent_time) * 1000, 1
                                        )
                                        self._last_speech_sent_time = 0.0
                                self._is_speaking = True
                                self.player.write(inline_data.data)

                            # Text transcript
                            text = getattr(part, "text", None)
                            if text and self.on_text_received:
                                self.on_text_received(text)

                    # Turn Completion
                    if getattr(server_content, "turn_complete", False):
                        self._is_speaking = False
                        first_audio_received = False
                        if self.on_turn_complete:
                            self.on_turn_complete()

                # 2. Tool Calls
                tool_call = getattr(message, "tool_call", None)
                if tool_call:
                    await self._handle_tool_call(tool_call)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ [GeminiLive] Receive loop error: {e}")
        finally:
            self._is_speaking = False

    async def _handle_tool_call(self, tool_call: Any):
        """Executes declared tools and delivers responses back to the Live session."""
        responses = []
        function_calls = getattr(tool_call, "function_calls", [])

        for fc in function_calls:
            call_id = getattr(fc, "id", "")
            func_name = getattr(fc, "name", "")
            args = getattr(fc, "args", {}) or {}

            print(f"🔧 [GeminiLive] Executing tool '{func_name}' [id: {call_id}] with args: {args}")

            tool_result: Dict[str, Any] = {}
            if func_name == "get_current_time":
                now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
                time_str = now_ist.strftime("%I:%M %p").lstrip("0")
                tool_result = {"time": time_str, "timezone": "IST (Asia/Kolkata)"}

            elif func_name == "get_current_date":
                now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
                date_str = now_ist.strftime("%A, %B %d, %Y")
                tool_result = {"date": date_str, "timezone": "IST (Asia/Kolkata)"}

            elif func_name == "desktop_open_application":
                app_name = args.get("app_name", "")
                desktop_svc = get_desktop_service()
                res = desktop_svc.open_application(app_name)
                tool_result = res

            elif func_name == "desktop_system_diagnostics":
                desktop_svc = get_desktop_service()
                res = desktop_svc.get_system_diagnostics()
                tool_result = res
            else:
                tool_result = {"error": f"Unknown tool: {func_name}"}

            responses.append(
                types.FunctionResponse(
                    name=func_name,
                    id=call_id,
                    response=tool_result,
                )
            )

        if responses:
            print(f"📤 [GeminiLive] Returning {len(responses)} tool responses to server...")
            await self.session.send_tool_response(function_responses=responses)

    def interrupt(self):
        """Locally interrupts playback."""
        self.player.abort()
        self._is_speaking = False

    async def disconnect(self):
        """Closes the live session cleanly."""
        self._running = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        self.player.abort()

        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_ctx = None
            self.session = None

        self._is_connected = False
        print("⏹️ [GeminiLive] Session closed.")
