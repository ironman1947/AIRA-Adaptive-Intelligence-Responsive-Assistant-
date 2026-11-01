"""Global pytest configuration and hermetic test fixtures for AIRA."""

import sys
from unittest.mock import MagicMock

# Stub sounddevice if PortAudio library is missing or import fails
try:
    import sounddevice
except (ImportError, OSError):
    sd_mock = MagicMock()
    sd_mock.RawOutputStream = MagicMock
    sd_mock.InputStream = MagicMock
    sys.modules["sounddevice"] = sd_mock
