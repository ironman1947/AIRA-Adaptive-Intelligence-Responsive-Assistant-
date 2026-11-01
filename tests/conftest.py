"""Global pytest configuration and hermetic test fixtures for AIRA."""

import sys
import json
import io
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# 1. Stub sounddevice if PortAudio library is missing or import fails
try:
    import sounddevice
except (ImportError, OSError):
    sd_mock = MagicMock()
    sd_mock.RawOutputStream = MagicMock
    sd_mock.InputStream = MagicMock
    sys.modules["sounddevice"] = sd_mock


def pytest_addoption(parser):
    """Add CLI options for live integration testing."""
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run live model / external API tests",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests marked @pytest.mark.live unless --run-live is passed."""
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="requires --run-live option and active credentials/service")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def mock_local_health(request, monkeypatch):
    """Mocks check_local_health to return False (no live Ollama) by default so tests don't hang."""
    if "live" in request.keywords:
        return

    import src.agent.router
    import src.agent.core
    import src.main

    async def _mock_offline():
        return False

    monkeypatch.setattr(src.agent.router, "check_local_health", _mock_offline)
    monkeypatch.setattr(src.agent.core, "check_local_health", _mock_offline)
    monkeypatch.setattr(src.main, "check_local_health", _mock_offline)


@pytest.fixture(autouse=True)
def mock_cloud_health_default(request, monkeypatch):
    """Mocks check_cloud_health to return True by default so workflows can route to cloud mock without hanging."""
    if "live" in request.keywords:
        return

    import src.agent.router
    import src.agent.core
    import src.main

    async def _mock_cloud_online():
        return True

    monkeypatch.setattr(src.agent.router, "check_cloud_health", _mock_cloud_online)
    monkeypatch.setattr(src.agent.core, "check_cloud_health", _mock_cloud_online)
    monkeypatch.setattr(src.main, "check_cloud_health", _mock_cloud_online)


@pytest.fixture(autouse=True)
def mock_openrouter_client(request, monkeypatch):
    """Fixture providing a deterministic mock for OpenRouter/Nebius client."""
    if "live" in request.keywords:
        return

    import src.agent.core

    mock_client = MagicMock()

    async def mock_create(**kwargs):
        messages = kwargs.get("messages", [])
        last_user_prompt = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user_prompt = str(m.get("content", ""))
                break

        tools = kwargs.get("tools")
        # Check if desktop action prompt
        if tools and any(k in last_user_prompt.lower() for k in ["open safari", "launch safari", "open application"]):
            tc = MagicMock()
            tc.id = "call_mock_safari_123"
            tc.function.name = "desktop_open_application"
            tc.function.arguments = json.dumps({"app_name": "Safari"})

            msg = MagicMock()
            msg.content = None
            msg.tool_calls = [tc]
            choice = MagicMock()
            choice.message = msg
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        # Follow-up message after tool execution
        if not tools and messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "tool":
            msg = MagicMock()
            msg.content = "Opening Safari requires user confirmation."
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        content = "Coordinated Universal Time (UTC) is the primary atomic timekeeping standard and epoch used globally."
        if "explain how rag works" in last_user_prompt.lower():
            content = "Retrieval-Augmented Generation (RAG) retrieves relevant documents and augments LLM generation."
        elif "personal ai agent" in last_user_prompt.lower():
            content = "According to recent studies [Local Reasoning in AI Agents 2026](https://arxiv.org/abs/2601.12345), local-first architectures minimize latency."

        msg = MagicMock()
        msg.content = content
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
    monkeypatch.setattr(src.agent.core, "get_nebius_client", lambda: mock_client)
    return mock_client


@pytest.fixture(autouse=True)
def mock_internet_tools(request):
    """Fixture mocking DDGS and requests.get for Wikipedia / arXiv fallback so tests never touch the network."""
    if "live" in request.keywords:
        yield
        return

    with patch("src.tools.internet.DDGS") as mock_ddgs, patch("requests.get") as mock_get:
        instance = mock_ddgs.return_value.__enter__.return_value
        instance.text.return_value = [
            {
                "title": "Hermetic Offline Research Result",
                "body": "Deterministic search content for hermetic testing.",
                "href": "https://example.com/offline-research",
            }
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "query": {
                "search": [
                    {
                        "title": "Hermetic Wikipedia Article",
                        "snippet": "Hermetic Wikipedia content for offline testing.",
                    }
                ]
            }
        }
        mock_resp.text = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <id>http://arxiv.org/abs/2601.00000</id>
                <title>Hermetic arXiv Paper</title>
                <summary>Hermetic summary for offline testing.</summary>
            </entry>
        </feed>"""
        mock_get.return_value = mock_resp

        yield {"mock_ddgs": mock_ddgs, "mock_get": mock_get}
