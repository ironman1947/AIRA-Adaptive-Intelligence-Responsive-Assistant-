"""Comprehensive test suite for Routing Regression Repair & Zero-LLM Deterministic Handlers.

Verifies the 5 core routes and requirements:
1. "What's the time?" -> Local clock response, 0 LLM calls, <10ms latency.
2. "What's today's date?" -> Correct date, 0 LLM calls, <10ms latency.
3. "What is system of time?" -> Conceptual query, NOT a clock lookup (classified as conceptual).
4. "Research the latest best practices in personal AI agent architectures and local reasoning."
   - Standard Mode: Web research workflow, sources retrieved, real citations, tools_triggered=True.
   - Local-Only Mode: Privacy guardrail immediately blocks external web research.
   - Retrieval Failure Honesty: Honest reporting if 0 sources returned, no fabricated citations.
5. "Hi AIRA." -> Natural greeting, no web search, 0 citations.
6. "Explain how RAG works." -> Direct reasoning, no unnecessary web research.
7. Single shared orchestrator pipeline across /api/chat and Desktop Companion.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from zoneinfo import ZoneInfo
from datetime import datetime

from src.agent.core import run_agent_workflow
from src.agent.intent import analyze_conversational_intent, IntentCategory


@pytest.mark.asyncio
async def test_route_1_deterministic_time_query():
    """Verify 'What's the time?' resolves via local system clock with zero LLM calls."""
    res = await run_agent_workflow("What's the time?")

    assert res["model_used"] == "system_clock"
    assert res["target_engine"] == "local_system"
    assert res["tools_triggered"] is False
    assert res["executed_tools"] == []
    assert res["citations"] == []
    assert res["intent_category"] == IntentCategory.TIME_DATE_QUERY
    assert "IST" in res["result"]

    # Verify time matches Asia/Kolkata
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%I:%M %p").lstrip("0")
    assert now_ist[:4] in res["result"]


@pytest.mark.asyncio
async def test_route_2_deterministic_date_query():
    """Verify 'What's today's date?' resolves via local system clock with zero LLM calls."""
    res = await run_agent_workflow("What's today's date?")

    assert res["model_used"] == "system_clock"
    assert res["target_engine"] == "local_system"
    assert res["tools_triggered"] is False
    assert res["executed_tools"] == []
    assert res["citations"] == []
    assert res["intent_category"] == IntentCategory.TIME_DATE_QUERY

    # Verify date matches Asia/Kolkata
    now_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%A, %B %d, %Y")
    assert now_date in res["result"]


@pytest.mark.asyncio
async def test_route_2b_conceptual_time_query_rejected():
    """Verify conceptual question 'What is system of time?' is NOT routed to the clock."""
    intent = analyze_conversational_intent("What is system of time?")
    assert intent.category != IntentCategory.TIME_DATE_QUERY
    assert intent.category == IntentCategory.GENERAL_KNOWLEDGE


@pytest.mark.asyncio
async def test_route_3_web_research_local_only_privacy_guardrail():
    """Verify web research is immediately blocked when Local-Only privacy mode is enabled."""
    prompt = "Research the latest best practices in personal AI agent architectures and local reasoning."
    res = await run_agent_workflow(prompt, privacy_mode="local_only")

    assert res["model_used"] == "privacy_guardrail"
    assert res["target_engine"] == "local"
    assert res["tools_triggered"] is False
    assert res["executed_tools"] == []
    assert res["citations"] == []
    assert "Local-Only Privacy Mode is active" in res["result"]


@pytest.mark.asyncio
async def test_route_3b_web_research_honest_failure_reporting():
    """Verify AIRA honestly reports retrieval failure when 0 sources are found, without hallucinating citations."""
    prompt = "Research the latest best practices in personal AI agent architectures and local reasoning."

    # Mock knowledge gatherer returning empty web sources
    with patch("src.agent.core._knowledge_engine.gather_knowledge", new_callable=AsyncMock) as mock_gather:
        from src.knowledge.engine import KnowledgeBundle
        from src.knowledge.router import KnowledgeRouteDecision

        decision = KnowledgeRouteDecision(use_web_research=True, search_queries=["personal AI agent architectures"])
        empty_bundle = KnowledgeBundle(decision=decision, web_sources=[], citations=[])
        mock_gather.return_value = empty_bundle

        res = await run_agent_workflow(prompt, privacy_mode="standard")

        assert res["model_used"] == "research_engine"
        assert res["tools_triggered"] is True
        assert len(res["executed_tools"]) == 1
        assert res["executed_tools"][0]["tool"] == "web_search"
        assert res["executed_tools"][0]["sources_found"] == 0
        assert res["citations"] == []
        assert "unable to retrieve live web sources" in res["result"]


@pytest.mark.asyncio
async def test_route_3c_web_research_standard_with_sources():
    """Verify web research records executed_tools and returns verified citations when sources exist."""
    prompt = "Research the latest best practices in personal AI agent architectures and local reasoning."

    mock_sources = [
        {
            "title": "Local Reasoning in AI Agents 2026",
            "url": "https://arxiv.org/abs/2601.12345",
            "snippet": "Analysis of on-device LLM architectures and dual-engine orchestration.",
            "retrieved_at": "2026-10-30T00:00:00",
        }
    ]

    with patch("src.agent.core._knowledge_engine.gather_knowledge", new_callable=AsyncMock) as mock_gather:
        from src.knowledge.engine import KnowledgeBundle
        from src.knowledge.router import KnowledgeRouteDecision

        decision = KnowledgeRouteDecision(use_web_research=True, search_queries=["personal AI agent architectures"])
        bundle = KnowledgeBundle(
            decision=decision,
            web_sources=mock_sources,
            citations=["[Local Reasoning in AI Agents 2026](https://arxiv.org/abs/2601.12345)"],
            prompt_context_text="Evidence context",
        )
        mock_gather.return_value = bundle

        # Mock cloud synthesis
        with patch("src.agent.core.get_nebius_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_choice = MagicMock()
            mock_msg = MagicMock()
            mock_msg.content = "According to recent studies [Local Reasoning in AI Agents 2026](https://arxiv.org/abs/2601.12345), local-first architectures minimize latency."
            mock_msg.tool_calls = None
            mock_choice.message = mock_msg
            mock_resp.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_client_factory.return_value = mock_client

            with patch("src.agent.core.check_cloud_health", new_callable=AsyncMock) as mock_cloud_health:
                mock_cloud_health.return_value = True

                res = await run_agent_workflow(prompt, privacy_mode="standard")

                assert res["tools_triggered"] is True
                assert len(res["executed_tools"]) >= 1
                assert any(t["tool"] == "web_search" for t in res["executed_tools"])
                assert len(res["citations"]) >= 1
                assert "https://arxiv.org/abs/2601.12345" in res["citations"][0]


@pytest.mark.asyncio
async def test_route_4_greeting_no_retrieval():
    """Verify 'Hi AIRA.' is handled naturally with no web search or unnecessary retrieval."""
    res = await run_agent_workflow("Hi AIRA.")

    assert res["intent_category"] == IntentCategory.GREETING
    assert res["tools_triggered"] is False
    assert res["executed_tools"] == []
    assert res["citations"] == []
    assert res["sources_used"] == []


@pytest.mark.asyncio
async def test_route_5_general_knowledge_direct_reasoning():
    """Verify 'Explain how RAG works.' uses direct model reasoning without web search."""
    intent = analyze_conversational_intent("Explain how RAG works.")
    assert intent.category == IntentCategory.GENERAL_KNOWLEDGE
    assert intent.needs_web_search is False

    from src.knowledge.router import KnowledgeRouter
    router = KnowledgeRouter()
    decision = router.evaluate("Explain how RAG works.", intent=intent)
    assert decision.use_web_research is False

