"""Tests for AIRA Intelligent Dual-Engine Routing and Privacy Enforcement."""

import pytest
from src.agent.router import determine_complexity, route_request

@pytest.mark.asyncio
async def test_deterministic_realtime_routing():
    # Real-time / search queries must route to HEAVY for web search tools
    assert await determine_complexity("What is the current news today?") == "HEAVY"
    assert await determine_complexity("Find the latest news on AI") == "HEAVY"
    assert await determine_complexity("Search for latest Python PEP releases") == "HEAVY"

@pytest.mark.asyncio
async def test_fastpath_greeting_routing():
    assert await determine_complexity("Hello AIRA") == "LOW"
    assert await determine_complexity("Hi there") == "LOW"

@pytest.mark.asyncio
async def test_privacy_mode_enforces_local_engine():
    res = await route_request(
        prompt="Write a Python script for a binary search tree",
        privacy_mode="local_only",
    )
    assert res["target_engine"] == "local"
    assert res["privacy_mode"] == "local_only"
    assert "Local-Only Privacy Policy" in res["reason"]

@pytest.mark.asyncio
async def test_standard_routing_escalation():
    res = await route_request(
        prompt="What is the latest news today?",
        privacy_mode="standard",
    )
    assert res["target_engine"] == "cloud"
    assert res["complexity"] == "HEAVY"
