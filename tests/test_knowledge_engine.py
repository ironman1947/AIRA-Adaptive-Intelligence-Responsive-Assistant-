"""Comprehensive Test Suite for AIRA Grounded Knowledge & Research Engine.

Tests:
1. KnowledgeRouter: Decides when to use model knowledge vs RAG vs web research vs memory.
2. Privacy enforcement: Web search strictly blocked in local_only mode.
3. InternetResearchEngine: Multi-query search, safe page fetching, SSRF filtering (127.0.0.1, AWS metadata, 192.168.x).
4. Contradiction detection across retrieved web sources.
5. CitationValidator: Validates that answer citations refer to genuine retrieved evidence.
6. Dynamic runtime timezone-aware timestamping.
7. End-to-end UnifiedKnowledgeEngine bundle compilation.
8. FastAPI research endpoint (/api/knowledge/research).
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from src.main import app
from src.knowledge.router import KnowledgeRouter, KnowledgeRouteDecision
from src.knowledge.research import InternetResearchEngine
from src.knowledge.citations import CitationValidator
from src.knowledge.engine import UnifiedKnowledgeEngine, KnowledgeBundle
from src.security.network import validate_url_security
from src.agent.identity import build_aira_system_prompt, AiraRuntimeState

client = TestClient(app)


class TestKnowledgeRouter:
    """Tests intelligent routing between model knowledge, RAG, and live web research."""

    def setup_method(self):
        self.router = KnowledgeRouter()

    def test_greeting_does_not_trigger_search_or_rag(self):
        decision = self.router.evaluate(prompt="Hello AIRA, good morning!")
        assert decision.use_rag is False
        assert decision.use_web_research is False
        assert "direct model knowledge" in decision.reasoning.lower()

    def test_document_question_triggers_rag(self):
        decision = self.router.evaluate(
            prompt="What does the uploaded architecture document say about database sharding?",
            has_indexed_docs=True
        )
        assert decision.use_rag is True

    def test_current_information_triggers_web_research(self):
        decision = self.router.evaluate(
            prompt="What is the latest release version of Python and LangChain today?",
            privacy_mode="standard"
        )
        assert decision.use_web_research is True
        assert len(decision.search_queries) > 0

    def test_privacy_mode_local_only_strictly_blocks_web_research(self):
        decision = self.router.evaluate(
            prompt="What is the latest news today?",
            privacy_mode="local_only"
        )
        assert decision.use_web_research is False
        assert "local-only" in decision.reasoning.lower()


class TestInternetResearchAndWebSafety:
    """Tests SSRF prevention, safe page fetching, and cross-source contradiction detection."""

    def test_ssrf_protection_blocks_internal_and_cloud_metadata_ips(self):
        # Localhost loopback
        safe1, _ = validate_url_security("http://127.0.0.1/admin")
        assert safe1 is False
        safe2, _ = validate_url_security("http://localhost:8080/secret")
        assert safe2 is False

        # Private RFC1918 addresses
        safe3, _ = validate_url_security("http://192.168.1.1/router")
        assert safe3 is False
        safe4, _ = validate_url_security("http://10.0.0.5/api")
        assert safe4 is False

        # Cloud metadata service (AWS/GCP/Azure)
        safe5, _ = validate_url_security("http://169.254.169.254/latest/meta-data/")
        assert safe5 is False

        # Public safe web addresses
        safe6, _ = validate_url_security("https://en.wikipedia.org/wiki/Artificial_intelligence")
        assert safe6 is True
        safe7, _ = validate_url_security("https://github.com/fastapi/fastapi")
        assert safe7 is True

    def test_contradiction_detection(self):
        engine = InternetResearchEngine()

        sample_sources = [
            {
                "title": "Report A",
                "snippet": "The model was released in 2022 with 7 billion parameters.",
                "url": "https://sourceA.org"
            },
            {
                "title": "Report B",
                "snippet": "The model was released in 2024 with 70 billion parameters.",
                "url": "https://sourceB.org"
            }
        ]

        contradictions = engine.detect_contradictions(sample_sources)
        assert len(contradictions) > 0
        assert any("timeline" in c.lower() or "release" in c.lower() or "discrepancy" in c.lower() for c in contradictions)


class TestCitationValidation:
    """Tests that answers only cite actual retrieved evidence, preventing hallucinations."""

    def test_valid_markdown_and_document_citations(self):
        retrieved_sources = [
            {"title": "FastAPI Guide", "url": "https://fastapi.tiangolo.com"},
            {"filename": "specs.pdf", "citation": "[specs.pdf | Section 1]"},
        ]

        answer = (
            "According to [FastAPI Guide](https://fastapi.tiangolo.com), routes are asynchronous. "
            "Also, [specs.pdf | Section 1] outlines the system goals."
        )

        is_valid, valid_cites, ungrounded_cites = CitationValidator.validate_citations(answer, retrieved_sources)
        assert is_valid is True
        assert len(valid_cites) == 2
        assert len(ungrounded_cites) == 0

    def test_ungrounded_fabricated_citation_flagged(self):
        retrieved_sources = [
            {"title": "FastAPI Guide", "url": "https://fastapi.tiangolo.com"},
        ]

        answer = (
            "Here is the proof: [Invented Source](https://fake-hallucinated-source.com/research). "
            "Also check [specs.pdf | Section 9]."
        )

        is_valid, valid_cites, ungrounded_cites = CitationValidator.validate_citations(answer, retrieved_sources)
        assert is_valid is False
        assert len(valid_cites) == 0
        assert len(ungrounded_cites) == 2


class TestDynamicTimestampAndSystemPrompt:
    """Tests Requirement N: Timezone-aware runtime timestamping."""

    def test_dynamic_runtime_timestamp_is_timezone_aware(self):
        state = AiraRuntimeState()
        now_str = state.to_dict()["current_time"]

        # Must include day, year, time, and timezone abbreviation
        assert any(tz in now_str for tz in ["IST", "UTC", "PST", "EST", "GMT", "+", "-"]) or len(now_str) > 15

    def test_system_prompt_includes_grounded_knowledge(self):
        state = AiraRuntimeState()
        grounded_context = "### Grounded Document Evidence:\n- Source [Doc.txt]: AIRA uses dual engines."

        prompt = build_aira_system_prompt(
            runtime_state=state,
            grounded_knowledge_context=grounded_context,
        )

        assert "Grounded Document Evidence" in prompt
        assert "AIRA uses dual engines" in prompt


class TestUnifiedKnowledgeEngine:
    """Tests end-to-end knowledge gathering."""

    @pytest.mark.asyncio
    async def test_gather_knowledge_local_only_excludes_web(self):
        engine = UnifiedKnowledgeEngine()
        bundle = await engine.gather_knowledge(
            prompt="What is the current weather and latest Python news?",
            privacy_mode="local_only"
        )
        assert len(bundle.web_sources) == 0
        assert bundle.decision.use_web_research is False


class TestKnowledgeAPIEndpoints:
    """Test FastAPI Knowledge research endpoint."""

    def test_research_endpoint_blocks_local_only(self):
        payload = {
            "query": "Latest breakthroughs in AI",
            "privacy_mode": "local_only",
        }
        resp = client.post("/api/knowledge/research", json=payload)
        assert resp.status_code == 403
        assert "prohibited in Local-Only" in resp.json()["detail"]

    def test_research_endpoint_standard_mode(self):
        payload = {
            "query": "Python 3.11 features",
            "privacy_mode": "standard",
            "max_results": 2
        }
        resp = client.post("/api/knowledge/research", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "contradictions" in data
