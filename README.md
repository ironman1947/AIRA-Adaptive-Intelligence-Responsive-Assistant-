# PROJECT AIRA (Adaptive Intelligence & Responsive Assistant)
> **Master Engineering Specification & Architectural Implementation**
> *General-Purpose Personal AI Companion, Intelligent Coworker, Researcher, and Autonomous Agent*

---

## 1. Executive Summary & Persona Identity

**AIRA** (**Adaptive Intelligence & Responsive Assistant**) is a general-purpose, context-aware, persistent personal AI assistant. Rather than assuming that every conversation is a coding or software engineering problem, AIRA understands user intent, conversational context, and relevant preferences before deciding how to respond.

- **Assistant Name**: AIRA
- **Expansion**: Adaptive Intelligence & Responsive Assistant
- **Version**: `1.0.0`
- **Persona Presentation**: Female-presenting, intelligent, calm, composed, warm, conversational, and subtly witty. Grounded in reality with machine-readable runtime state awareness (`AiraRuntimeState`). Never claims biological consciousness or subjective feelings.
- **Capabilities Scope**:
  1. **Personal AI Companion**: Natural conversation, active listening, and conversational continuity.
  2. **General Knowledge & Learning**: Clear explanations across science, humanities, and history.
  3. **Emotional Attentiveness**: Tactful acknowledgment of frustration, excitement, and exhaustion without psychological diagnoses.
  4. **Personal Productivity**: Daily planning, brainstorming, and goal structuring.
  5. **Coding & Engineering Coworker**: Sandboxed workspace inspection, unified diff generation, and test execution when requested.
  6. **Research & Fact Verification**: Real-time DuckDuckGo search with citations and SSRF protection.
  7. **Personal Knowledge Management (RAG)**: Ingestion and semantic retrieval across TXT, Markdown, PDF, and DOCX documents.
  8. **Operational Constitution**: Seven robotics-inspired laws enforced at the Python execution layer with human-in-the-loop oversight.

---

## 2. Intent-Aware Architecture & Conversational Intelligence

AIRA incorporates a dedicated **Conversational Intelligence Subsystem** (`src/agent/intent.py`) that analyzes each user turn across multiple dimensions:

```
                            [User Request]
                                  │
                                  ▼
                ┌───────────────────────────────────┐
                │ Conversational Intelligence Layer │
                │        (src/agent/intent.py)      │
                └─────────────────┬─────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Intent Category  │    │  Emotional Cues  │    │  Context Needs   │
│ • Greeting       │    │ • Frustrated     │    │ • Needs Project? │
│ • Casual Chat    │    │ • Excited        │    │ • Needs Search?  │
│ • Continuation   │    │ • Exhausted      │    │ • Needs Tools?   │
│ • Gen Knowledge  │    │ • Confused       │    │ • Needs RAG?     │
│ • Emotional      │    │ • Reflective     │    │ • Clarification? │
│ • Creative       │    │ • Neutral        │    └──────────────────┘
│ • Coding/Tech    │    └──────────────────┘
│ • Web Research   │
└──────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Context & Prompt Assembler                     │
│ • Greetings: Natural, warm reply. NO project context injected!   │
│ • Casual: Brief, friendly. NO engineering reports!               │
│ • Continuation: Seamlessly resume recent work or clarify.       │
│ • Frustration: Empathetic acknowledgment & calm troubleshooting. │
│ • Technical: Precise, structured reasoning with verified tools.  │
└─────────────────────────────────┬────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Dual-Engine Intelligent Router                  │
│ • Local Engine (Ollama / Gemma 2B): Casual, Knowledge, Private   │
│ • Cloud Engine (Nemotron 550B): Tool-intensive, Deep Reasoning   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
hackathon-agent/
├── .env.example                          # Documented environment template with placeholders
├── .gitignore                            # Protected paths (.env, databases, storage, caches)
├── pyproject.toml                        # Project metadata, dependencies, and pytest configuration
├── Dockerfile                            # Multi-stage production container definition
├── README.md                             # Comprehensive technical manual & operational guide
├── frontend.py                           # Modern multi-tab Streamlit dashboard
├── .streamlit/
│   └── config.toml                       # Styled dark-mode theme & server configuration
├── data/
│   └── aira.db                           # SQLite persistent memory, RAG index & audit logs
├── storage/
│   └── uploads/                          # Scoped document ingestion storage
├── src/
│   ├── config.py                         # Unified runtime & environment settings
│   ├── main.py                           # FastAPI REST API endpoints
│   ├── agent/
│   │   ├── core.py                       # AIRA central orchestrator
│   │   ├── identity.py                   # AIRA persona, AiraRuntimeState & system prompt builder
│   │   ├── intent.py                     # Conversational intelligence & intent classification
│   │   ├── prompts.py                    # Classification, session summary & error prompts
│   │   ├── router.py                     # Dual-engine router with privacy & health checks
│   │   └── state.py                      # Active in-memory session tracking
│   ├── coding/
│   │   ├── workspace.py                  # Workspace tree scan & sandboxed file reader
│   │   ├── editor.py                     # Unified diff generator & safe file modification
│   │   └── tester.py                     # Subprocess pytest runner with outcome parsing
│   ├── context/
│   │   ├── user_profile.py               # User profile manager (no fabricated defaults)
│   │   ├── project_context.py            # Isolated project workspace coordinator
│   │   └── session_continuity.py         # Session summaries & context retrieval
│   ├── evaluation/
│   │   ├── feedback.py                   # Feedback collection & candidate procedural learning
│   │   └── eval_runner.py                # Integrated benchmark evaluation runner
│   ├── memory/
│   │   ├── database.py                   # SQLite schema manager with indexes & foreign keys
│   │   ├── models.py                     # Pydantic schemas for memories, projects & logs
│   │   └── repository.py                 # CRUD repository abstractions & JSON export
│   ├── rag/
│   │   ├── ingestion.py                  # Document parser (TXT, MD, PDF, DOCX) & chunker
│   │   └── store.py                      # TF-IDF vector & semantic store in SQLite with citations
│   ├── security/
│   │   ├── audit.py                      # Audit service with regex credential redaction
│   │   ├── constitution.py               # The 7 robotics-inspired operational principles
│   │   ├── network.py                    # SSRF, loopback, and private IP blocking
│   │   └── policy.py                     # Policy decision engine & human approval gates
│   ├── tools/
│   │   ├── internet.py                   # DuckDuckGo search & safe webpage fetcher
│   │   ├── logic_eval.py                 # AST-based safe math & logic evaluator
│   │   └── registry.py                   # Central tool registry with OpenAI function schemas
│   └── voice/
│       └── interfaces.py                 # STT, TTS, wake word & turn management abstractions
└── tests/
    ├── test_api.py                       # FastAPI REST endpoint integration tests
    ├── test_coding_coworker.py           # Workspace inspection, diffs & pytest runner tests
    ├── test_constitution_and_policy.py  # Security laws, SSRF prevention & policy checks
    ├── test_conversational_intelligence.py # 20 Conversational acceptance criteria tests
    ├── test_evaluation.py                # Feedback metrics & benchmark evaluation tests
    ├── test_identity.py                  # AIRA identity, runtime state & prompt tests
    ├── test_internet_tools.py            # Web search, safe fetch & logic evaluation tests
    ├── test_memory_repository.py         # SQLite memory CRUD & app restart persistence tests
    ├── test_rag.py                       # RAG parsing, chunking, search & project isolation tests
    └── test_router.py                    # Routing complexity & privacy enforcement tests
```

---

## 4. Protected Operational Constitution (Robotics-Inspired Laws)

AIRA is governed by seven immutable operational principles enforced at the Python execution layer:

| Law | Principle | Description & Enforcement |
|---|---|---|
| **1** | **Human Safety & Harm Prevention** | Never knowingly cause harm, generate malware, or assist in unsafe activities. Enforced via hard barriers in the policy engine. |
| **2** | **Authorized Instructions** | Follow legitimate user instructions faithfully unless they conflict with higher safety or privacy constraints. |
| **3** | **Privacy & Confidentiality** | Protect private files, credentials, and memory. Enforced via credential redaction in logs and Local-Only privacy mode. |
| **4** | **Honesty & Evidentiary Grounding** | Distinguish verified facts, citations, uncertainty, and unverified model outputs. Never claim a tool was used unless it succeeded. |
| **5** | **Human Oversight** | Consequential operations (modifying project code, running tests, destructive actions) require explicit human approval. |
| **6** | **Bounded Autonomy** | Operate strictly within authorized workspace bounds; cannot expand privileges or disable safeguards. Path traversal is rejected. |
| **7** | **Reliability & Audit Accountability** | Report failures honestly and record all policy checks in an immutable, credential-redacted SQLite audit trail. |

---

## 5. User Understanding & Honest Personalization

AIRA does not attempt to simulate understanding through fabricated profile defaults:
1. **Explicit vs. Inferred**: Explicit profile entries (e.g. preferred name, communication style) are set by the user. Inferred preferences remain unconfirmed candidates with confidence metrics until confirmed.
2. **No Invented Titles**: Unknown fields are strictly shown as `"Not configured"` rather than inventing titles such as "Senior Software Engineer" or default programming languages.
3. **Situational vs. Permanent**: A temporary message of frustration is met with empathy, not turned into a permanent personality label.
4. **Context Isolation**: When greeting AIRA ("hhi", "hello"), stored project objectives are never displayed or injected into the prompt.

---

## 6. Installation & Execution (macOS)

```bash
# Terminal 1: FastAPI Backend
source .venv/bin/activate
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload

# Terminal 2: Streamlit Interface
source .venv/bin/activate
streamlit run frontend.py --server.port 8501
```

- Streamlit Web App: `http://localhost:8501`
- FastAPI Documentation: `http://localhost:8080/docs`

---

## 7. Automated Testing Results

All 60 automated unit, integration, and conversational intelligence tests pass with a 100% success rate:

```
============================== 60 passed in 3.26s ==============================
```
