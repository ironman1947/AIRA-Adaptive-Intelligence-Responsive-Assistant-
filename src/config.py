import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------------------
# Cloud Engine Configuration
# ------------------------------------------------------------------------------
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://openrouter.ai/api/v1")
HEAVY_MODEL = os.getenv("HEAVY_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

# ------------------------------------------------------------------------------
# Local Engine Configuration
# ------------------------------------------------------------------------------
USE_LOCAL_ROUTER = os.getenv("USE_LOCAL_ROUTER", "true").lower() == "true"
LOCAL_BASE_URL = os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "gemma:2b")
CLOUD_LIGHT_MODEL = os.getenv("CLOUD_LIGHT_MODEL", "google/gemma-2-9b-it")

# ------------------------------------------------------------------------------
# AIRA Operational & Privacy Settings
# ------------------------------------------------------------------------------
FORCE_LOCAL_ONLY = os.getenv("FORCE_LOCAL_ONLY", "false").lower() == "true"
DEFAULT_PRIVACY_LEVEL = os.getenv("DEFAULT_PRIVACY_LEVEL", "standard")

# ------------------------------------------------------------------------------
# Storage and Persistence
# ------------------------------------------------------------------------------
AIRA_DB_PATH = os.getenv("AIRA_DB_PATH", str(BASE_DIR / "data" / "aira.db"))
AIRA_STORAGE_DIR = os.getenv("AIRA_STORAGE_DIR", str(BASE_DIR / "storage"))

# Ensure data and storage directories exist
Path(AIRA_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(AIRA_STORAGE_DIR).mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------------------
# Web Research & Security
# ------------------------------------------------------------------------------
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
WEB_FETCH_TIMEOUT_SECONDS = int(os.getenv("WEB_FETCH_TIMEOUT_SECONDS", "10"))
WEB_MAX_RESPONSE_BYTES = int(os.getenv("WEB_MAX_RESPONSE_BYTES", "1048576"))  # 1 MB

# ------------------------------------------------------------------------------
# Voice & Neural TTS Configuration
# ------------------------------------------------------------------------------
AIRA_TTS_PROVIDER = os.getenv("AIRA_TTS_PROVIDER", "elevenlabs").lower()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
ELEVENLABS_TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")

# ------------------------------------------------------------------------------
# API Security
# ------------------------------------------------------------------------------
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8501,http://127.0.0.1:8501"
    ).split(",")
    if origin.strip()
]

# ------------------------------------------------------------------------------
# Server Settings
# ------------------------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
