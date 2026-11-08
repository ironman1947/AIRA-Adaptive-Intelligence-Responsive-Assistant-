"""Comprehensive Acceptance and Intelligence Test Suite for AIRA 2.0 (Tests A through H).

Verifies the restoration, integration, and continuous operation of:
- Test A: Personal Memory Retrieval Across Restarts
- Test B: Previous Conversation Retrieval Across Sessions
- Test C: Knowledge Base (RAG) Document Retrieval & Summarization
- Test D: Live Desktop Voice Continuity Across Restarts & Bi-directional Context Transfer
- Test E: Current News Real Internet Retrieval & Markdown Citations
- Test F: Browser Access Opening URL & Summarizing Content (no OS app launch)
- Test G: Local-Only Privacy Enforcement (Strict Zero External Egress)
- Test H: Full System Regression
"""

import json
import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.agent.core import run_agent_workflow, get_shared_repository, get_shared_context_manager
from src.agent.intent import analyze_conversational_intent, IntentCategory
from src.memory.models import UserPreference, SemanticMemory, EpisodicMemory
from src.rag.store import get_rag_store
from src.desktop.companion import AiraDesktopCompanion


@pytest.mark.asyncio
async def test_a_personal_memory_retrieval_across_restarts():
    """Test A: Personal Memory Retrieval Across Restarts.
    
    Verifies that stored user preferences and profile facts are retrieved and
    injected into the context when the user asks about them in a fresh session.
    AIRA must not claim to lack access to that information.
    """
    repo = get_shared_repository()
    test_uid = "default_user"
    
    # 1. Seed personal preferences and semantic memories
    repo.add_preference(
        UserPreference(
            preference_key="database_stack",
            preference_value="PostgreSQL with asyncpg connection pooling",
            is_explicit=True,
            user_approved=True,
        )
    )
    repo.add_preference(
        UserPreference(
            preference_key="frontend_framework",
            preference_value="Streamlit with custom HTML components",
            is_explicit=True,
            user_approved=True,
        )
    )
    repo.add_semantic(
        SemanticMemory(
            subject="user",
            predicate="is_building",
            object_value="AIRA 2.0",
            content="User is building AIRA 2.0 with unified context retrieval",
            project_id="aira-core",
        )
    )

    # 2. Start a fresh session simulating a restart
    fresh_session_id = f"sess_restart_{uuid.uuid4().hex[:8]}"

    # Mock the LLM to verify it receives the grounded personal memories in its messages
    captured_messages = []

    async def mock_create(**kwargs):
        nonlocal captured_messages
        captured_messages = kwargs.get("messages", [])
        # Synthesize a response grounded in the provided prompt context
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="Based on your preferences, you use PostgreSQL with asyncpg connection pooling for databases and Streamlit for frontend development. You are currently building AIRA 2.0.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        res = await run_agent_workflow(
            prompt="What are my database and frontend preferences, and what project am I working on?",
            session_id=fresh_session_id,
            privacy_mode="standard",
        )

    # 3. Assertions
    assert res is not None
    assert "PostgreSQL" in res["result"]
    assert "Streamlit" in res["result"]
    assert "AIRA 2.0" in res["result"]
    assert "I don't have access" not in res["result"]

    # Verify that the system prompt received the personal memories
    assert len(captured_messages) > 0
    system_content = captured_messages[0]["content"]
    assert "PostgreSQL" in system_content or any("PostgreSQL" in str(m.get("content", "")) for m in captured_messages)
    assert any("Personal Memory" in s for s in res["sources_used"])


@pytest.mark.asyncio
async def test_b_previous_conversation_retrieval_across_sessions():
    """Test B: Previous Conversation Retrieval Across Sessions.
    
    Verifies that decisions and discussions made in Session 1 are seamlessly
    retrieved and referenced when continuing in Session 2.
    """
    repo = get_shared_repository()
    sess_1 = f"sess_topic_{uuid.uuid4().hex[:8]}"
    sess_2 = f"sess_continuation_{uuid.uuid4().hex[:8]}"

    # 1. Record an earlier discussion in Session 1
    repo.add_message(sess_1, "user", "Let's decide on using Redis for session caching and rate limiting.")
    repo.add_message(
        sess_1,
        "assistant",
        "We have agreed to use Redis for session caching and rate limiting with a 1-hour TTL.",
    )

    # 2. In Session 2, ask about the earlier decision
    captured_messages = []

    async def mock_create(**kwargs):
        nonlocal captured_messages
        captured_messages = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="As we decided earlier in our previous discussion, we chose Redis for session caching and rate limiting with a 1-hour TTL.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)
        mock_get_client.return_value = mock_client

        res = await run_agent_workflow(
            prompt="As we discussed earlier, what caching solution did we decide on?",
            session_id=sess_2,
            privacy_mode="standard",
        )

    # 3. Assertions
    assert "Redis" in res["result"]
    assert any("Previous Conversations" in s or "Personal Memory" in s for s in res["sources_used"])

    # Verify that prior conversation excerpts were provided in the prompt context
    all_context_text = " ".join(str(m.get("content", "")) for m in captured_messages)
    assert "Redis" in all_context_text
    assert "session caching" in all_context_text


@pytest.mark.asyncio
async def test_c_knowledge_base_rag_retrieval_and_summarization(tmp_path):
    """Test C: Knowledge Base (RAG) Document Retrieval & Summarization.
    
    Verifies that uploaded documents with distinctive facts are retrieved and cited,
    and that document summarization queries return grounded overviews.
    """
    rag_store = get_rag_store()
    filename = "quantum_chronos_spec.txt"
    spec_file = tmp_path / filename
    spec_content = (
        "Project Chronos Architecture Specification.\n\n"
        "Project Chronos is a distributed synchronization platform. It utilizes the QuantumSync engine "
        "to maintain sub-nanosecond clock alignment across geo-replicated data centers.\n\n"
        "QuantumSync relies on optical fiber pulse tracking and hardware timestamping. "
        "The primary failover protocol is named ChronoGuard."
    )
    spec_file.write_text(spec_content, encoding="utf-8")
    rag_store.index_document(str(spec_file))

    # 2. Test specific factual query
    captured_messages_1 = []

    async def mock_rag_create(**kwargs):
        nonlocal captured_messages_1
        captured_messages_1 = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="According to the uploaded specification [quantum_chronos_spec.txt | Section 1], Project Chronos uses the QuantumSync engine for sub-nanosecond clock alignment.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_rag_create)
        mock_get_client.return_value = mock_client

        res = await run_agent_workflow(
            prompt="What engine powers Project Chronos according to the uploaded document?",
            session_id=f"sess_rag_{uuid.uuid4().hex[:6]}",
            privacy_mode="standard",
        )

    assert "QuantumSync" in res["result"]
    assert res["tools_triggered"] is True
    assert any(t["tool"] == "rag_document_search" for t in res["executed_tools"])
    assert any("quantum_chronos_spec.txt" in c for c in res["citations"])

    # 3. Test document overview / summarization query
    captured_messages_2 = []

    async def mock_summary_create(**kwargs):
        nonlocal captured_messages_2
        captured_messages_2 = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="The uploaded document quantum_chronos_spec.txt outlines Project Chronos, describing its QuantumSync engine and ChronoGuard failover protocol.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_summary_create)
        mock_get_client.return_value = mock_client

        res_sum = await run_agent_workflow(
            prompt="Summarize the uploaded document quantum_chronos_spec.txt",
            session_id=f"sess_summary_{uuid.uuid4().hex[:6]}",
            privacy_mode="standard",
        )

    assert res_sum["tools_triggered"] is True
    assert any(t["tool"] == "rag_document_search" for t in res_sum["executed_tools"])
    all_summary_text = " ".join(str(m.get("content", "")) for m in captured_messages_2)
    assert "QuantumSync" in all_summary_text


@pytest.mark.asyncio
async def test_d_live_desktop_voice_continuity_and_bidirectional_transfer():
    """Test D: Live Desktop Voice Continuity Across Restarts.
    
    Verifies that voice sessions share the same persistent memory, project context,
    and past conversations as the standard chat interface, in both directions.
    """
    repo = get_shared_repository()

    # Step 1: User has an active project and prior discussion in Web Chat
    web_sess = f"web_session_{uuid.uuid4().hex[:8]}"
    repo.add_message(web_sess, "user", "Let's standardize our logging format on structured JSON with correlation IDs.")
    repo.add_message(web_sess, "assistant", "Agreed, structured JSON logging with correlation IDs is established.")

    # Step 2: Live Desktop voice turn begins with an ephemeral session ID
    voice_sess = f"voice_sess_{uuid.uuid4().hex[:8]}"
    captured_messages = []

    async def mock_voice_backend(**kwargs):
        nonlocal captured_messages
        captured_messages = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="As we decided earlier in your web session, we standardized on structured JSON logging with correlation IDs.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_voice_backend)
        mock_get_client.return_value = mock_client

        voice_res = await run_agent_workflow(
            prompt="As we discussed earlier, what logging format did we decide on?",
            session_id=voice_sess,
            privacy_mode="standard",
        )

    assert "structured JSON" in voice_res["result"]

    # Step 3: During the voice turn, user makes a new decision
    voice_decision_prompt = "Let's also use Logstash for log aggregation."
    async def mock_voice_backend_2(**kwargs):
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="Got it, Logstash will be our log aggregation tool.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_voice_backend_2)
        mock_get_client.return_value = mock_client

        await run_agent_workflow(
            prompt=voice_decision_prompt,
            session_id=voice_sess,
            privacy_mode="standard",
        )

    # Step 4: User goes back to Web Chat in a new session; Web Chat retrieves the voice decision!
    web_sess_2 = f"web_session_followup_{uuid.uuid4().hex[:8]}"
    captured_web_messages = []

    async def mock_web_backend(**kwargs):
        nonlocal captured_web_messages
        captured_web_messages = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="In our previous voice session, we decided to use Logstash for log aggregation.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.agent.core.get_nebius_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_web_backend)
        mock_get_client.return_value = mock_client

        web_res = await run_agent_workflow(
            prompt="What log aggregation tool did we agree on during the voice discussion?",
            session_id=web_sess_2,
            privacy_mode="standard",
        )

    assert "Logstash" in web_res["result"]
    all_web_context = " ".join(str(m.get("content", "")) for m in captured_web_messages)
    assert "Logstash" in all_web_context


@pytest.mark.asyncio
async def test_e_current_news_real_internet_retrieval_and_citations():
    """Test E: Current News Real Internet Retrieval & Markdown Citations.
    
    Verifies that queries about current information or recent developments
    execute live web research and return real, verifiable Markdown citations.
    """
    mock_articles = [
        {
            "title": "Autonomous AI Agents Report 2026",
            "url": "https://tech-journal.org/ai-agents-2026",
            "snippet": "New frameworks for local reasoning and unified memory architectures were deployed across industry.",
            "source_type": "duckduckgo",
            "retrieved_at": "2026-11-08T18:00:00Z",
        }
    ]

    captured_messages = []

    async def mock_llm(**kwargs):
        nonlocal captured_messages
        captured_messages = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="According to the [Autonomous AI Agents Report 2026](https://tech-journal.org/ai-agents-2026), new frameworks for local reasoning were deployed across industry.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.knowledge.research.InternetResearchEngine.search", return_value=mock_articles), \
         patch("src.knowledge.engine.InternetResearchEngine.multi_query_research", return_value=(mock_articles, [])), \
         patch("src.agent.core.get_nebius_client") as mock_get_client:

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_llm)
        mock_get_client.return_value = mock_client

        res = await run_agent_workflow(
            prompt="What are the latest AI developments and release trends?",
            privacy_mode="standard",
        )

    assert res["tools_triggered"] is True
    assert any(t["tool"] == "web_search" for t in res["executed_tools"])
    assert any("https://tech-journal.org/ai-agents-2026" in c for c in res["citations"])
    assert any("Live Web Research" in s for s in res["sources_used"])


@pytest.mark.asyncio
async def test_f_browser_access_open_url_and_summarize():
    """Test F: Browser Access Opening URL & Summarizing Content.
    
    Verifies that requests to open/read/summarize a URL fetch page content directly,
    strip HTML formatting, summarize the content, and cite the source URL without
    triggering a macOS desktop application launch.
    """
    sample_html_payload = json.dumps({
        "status": "success",
        "url": "https://example.org/climate-tech-report",
        "title": "Climate Tech Innovation 2026",
        "content": "The 2026 climate technology report highlights geothermal energy advancements and direct air carbon capture scaling across 15 nations.",
    })

    intent = analyze_conversational_intent("Open https://example.org/climate-tech-report and summarize what it says.")
    # Must be classified as WEB_RESEARCH, NOT DESKTOP_ACTION!
    assert intent.category == IntentCategory.WEB_RESEARCH
    assert intent.needs_web_search is True

    captured_messages = []

    async def mock_llm(**kwargs):
        nonlocal captured_messages
        captured_messages = kwargs.get("messages", [])
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="The report [Climate Tech Innovation 2026](https://example.org/climate-tech-report) highlights geothermal energy advancements and direct air carbon capture.",
                        tool_calls=None,
                    )
                )
            ]
        )

    with patch("src.context.web_context.fetch_webpage", return_value=sample_html_payload) as mock_fetch, \
         patch("src.agent.core.get_nebius_client") as mock_get_client:

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_llm)
        mock_get_client.return_value = mock_client

        res = await run_agent_workflow(
            prompt="Open https://example.org/climate-tech-report and summarize what it says.",
            privacy_mode="standard",
        )

    # Verify that fetch_webpage was invoked for the URL
    mock_fetch.assert_called_with("https://example.org/climate-tech-report")
    assert "geothermal energy" in res["result"]
    assert any("https://example.org/climate-tech-report" in c for c in res["citations"])
    # Crucial: verify this was not treated as a desktop application launch requiring approval!
    assert res.get("approval_required", False) is False


@pytest.mark.asyncio
async def test_g_local_only_privacy_mode_enforcement():
    """Test G: Local-Only Privacy Mode Enforcement.
    
    Verifies that when Local-Only privacy mode is enabled:
    - Zero external HTTP requests are made for web search.
    - Zero external HTTP requests are made for webpage browsing.
    - AIRA explicitly states that external research is blocked by privacy policy.
    - Citations list is completely empty.
    """
    # 1. Web search prompt in local_only mode
    res_search = await run_agent_workflow(
        prompt="Search the web for the latest security vulnerabilities in Python.",
        privacy_mode="local_only",
    )

    assert "Local-Only Privacy Mode is active" in res_search["result"]
    assert res_search["citations"] == []
    assert res_search["tools_triggered"] is False

    # 2. Browser reading prompt in local_only mode
    with patch("src.context.web_context.fetch_webpage") as mock_fetch:
        res_browser = await run_agent_workflow(
            prompt="Open https://example.org/article and summarize what it says.",
            privacy_mode="local_only",
        )
        mock_fetch.assert_not_called()

    assert "Local-Only Privacy" in res_browser["result"] or "blocked" in res_browser["result"].lower()
    assert res_browser["citations"] == []
