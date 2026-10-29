"""AIRA Core Orchestrator.

Combines identity, runtime state, conversational intent analysis,
context engine (user profile, project workspace, session continuity),
persistent memory, operational constitution, and dual-engine routing.
"""

import json
import uuid
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

from src.agent.identity import (
    AiraRuntimeState,
    build_aira_system_prompt,
    ASSISTANT_NAME,
)
from src.agent.identity_handler import (
    generate_assistant_name_response,
    generate_user_name_response,
    generate_introduction_response,
)
from src.agent.intent import IntentCategory, ConversationalIntent
from src.agent.router import (
    nebius_client,
    light_client,
    get_nebius_client,
    get_light_client,
    active_light_model,
    route_request,
    check_local_health,
    check_cloud_health,
)
from src.agent.state import get_or_create_session
from src.config import HEAVY_MODEL, BASE_DIR
from src.memory.repository import MemoryRepository, get_db_manager
from src.memory.models import EpisodicMemory, SemanticMemory
from src.context.user_profile import UserProfileManager
from src.context.project_context import ProjectContextManager
from src.context.session_continuity import SessionContinuityEngine
from src.security.audit import AuditService
from src.security.policy import PolicyDecisionEngine
from src.tools.registry import ToolRegistry
from src.rag.store import get_rag_store
from src.knowledge.engine import UnifiedKnowledgeEngine, KnowledgeBundle

# Shared singleton components
_repo = MemoryRepository(get_db_manager())
_user_profile_mgr = UserProfileManager(_repo)
_project_mgr = ProjectContextManager(_repo)
_session_mgr = SessionContinuityEngine(_repo)
_audit_service = AuditService(_repo)
_policy_engine = PolicyDecisionEngine(_audit_service)
_tool_registry = ToolRegistry(workspace_root=str(BASE_DIR), memory_repo=_repo)
_rag_store = get_rag_store()
_knowledge_engine = UnifiedKnowledgeEngine(
    rag_store=_rag_store,
    memory_repo=_repo,
    project_mgr=_project_mgr,
)

def _save_turn(sess_id: str, prompt: str, result_text: str):
    """Persists a user-assistant conversation turn in SQLite."""
    if sess_id and prompt and result_text:
        _repo.add_conversation_message(sess_id, role="user", content=prompt)
        _repo.add_conversation_message(sess_id, role="assistant", content=result_text)

def try_dispatch_deterministic_utility(
    prompt: str,
    intent: ConversationalIntent,
    request_id: str,
    sess_id: str,
    session_state: Any,
    user_profile_mgr: UserProfileManager,
    policy_engine: PolicyDecisionEngine,
    active_privacy: str,
    active_proj_id: Optional[str],
    start_time: float,
) -> Optional[Dict[str, Any]]:
    """Evaluates and dispatches unambiguous deterministic operations before LLM invocation.

    Guarantees:
    - Current time and date queries are resolved from local timezone-aware clock (Asia/Kolkata).
    - Authoritative identity and user introduction queries are resolved deterministically.
    - Zero LLM calls (neither local nor cloud).
    - Zero external network requests or RAG latency.
    """
    user_display_name = user_profile_mgr.get_user_display_name()

    # 1. Deterministic System Time & Date Query (Local Asia/Kolkata runtime clock)
    if intent.category == IntentCategory.TIME_DATE_QUERY:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
        except Exception:
            now = datetime.now()

        time_str = now.strftime("%I:%M %p").lstrip("0")
        date_str = now.strftime("%A, %B %d, %Y")

        clean_p = prompt.lower().strip()
        is_date_only = ("date" in clean_p or "day" in clean_p) and ("time" not in clean_p)
        is_time_only = ("time" in clean_p) and ("date" not in clean_p) and ("day" not in clean_p)

        if is_date_only:
            answer = f"Today's date is {date_str}."
        elif is_time_only:
            answer = f"The current system time is {time_str} IST."
        else:
            answer = f"The current system time is {time_str} IST on {date_str}."

        _save_turn(sess_id, prompt, answer)
        session_state.interaction_count += 1
        duration_ms = round((time.time() - start_time) * 1000, 2)
        print(f"📡 [AIRA Pipeline] ID: {request_id} | Intent: {intent.category} | Path: local_system | Model: system_clock | Tools: none | Duration: {duration_ms}ms")

        runtime_state = AiraRuntimeState(
            privacy_mode=active_privacy,
            active_project_id=active_proj_id,
            active_session_id=sess_id,
            user_display_name=user_display_name,
            pending_approvals=len(policy_engine.pending_approvals),
        )

        return {
            "request_id": request_id,
            "model_used": "system_clock",
            "complexity": "LOW",
            "intent_category": intent.category,
            "target_engine": "local_system",
            "tools_triggered": False,
            "executed_tools": [],
            "citations": [],
            "result": answer,
            "routing_reason": "Direct system time/date query resolved deterministically from local runtime clock.",
            "runtime_state": runtime_state.to_dict(),
            "duration_ms": duration_ms,
        }

    # 2. Authoritative Assistant / User Identity Inquiries
    if intent.identity_query_type:
        if intent.identity_query_type == "ask_assistant_name":
            answer = generate_assistant_name_response(user_display_name)
        else:
            answer = generate_user_name_response(user_display_name)

        _save_turn(sess_id, prompt, answer)
        session_state.interaction_count += 1
        duration_ms = round((time.time() - start_time) * 1000, 2)
        print(f"📡 [AIRA Pipeline] ID: {request_id} | Intent: {intent.category} | Path: local_identity | Model: identity_engine | Tools: none | Duration: {duration_ms}ms")

        runtime_state = AiraRuntimeState(
            privacy_mode=active_privacy,
            active_project_id=active_proj_id,
            active_session_id=sess_id,
            user_display_name=user_display_name,
            pending_approvals=len(policy_engine.pending_approvals),
        )

        return {
            "request_id": request_id,
            "model_used": "authoritative_identity",
            "complexity": "LOW",
            "intent_category": intent.category,
            "target_engine": "local_identity",
            "tools_triggered": False,
            "executed_tools": [],
            "citations": [],
            "result": answer,
            "routing_reason": "Direct identity inquiry resolved via authoritative identity engine.",
            "runtime_state": runtime_state.to_dict(),
            "duration_ms": duration_ms,
        }

    # 3. Explicit User Introductions & Name Updates
    if intent.category == IntentCategory.USER_INTRODUCTION and intent.extracted_user_name:
        user_profile_mgr.set_user_display_name(intent.extracted_user_name)
        answer = generate_introduction_response(
            name=intent.extracted_user_name,
            is_correction=intent.is_name_correction
        )
        _save_turn(sess_id, prompt, answer)
        session_state.interaction_count += 1
        duration_ms = round((time.time() - start_time) * 1000, 2)
        print(f"📡 [AIRA Pipeline] ID: {request_id} | Intent: {intent.category} | Path: local_intro | Model: identity_engine | Tools: none | Duration: {duration_ms}ms")

        runtime_state = AiraRuntimeState(
            privacy_mode=active_privacy,
            active_project_id=active_proj_id,
            active_session_id=sess_id,
            user_display_name=intent.extracted_user_name,
            pending_approvals=len(policy_engine.pending_approvals),
        )

        return {
            "request_id": request_id,
            "model_used": "authoritative_identity",
            "complexity": "LOW",
            "intent_category": intent.category,
            "target_engine": "local_identity",
            "tools_triggered": False,
            "executed_tools": [],
            "citations": [],
            "result": answer,
            "routing_reason": "User introduction recognized and saved to profile.",
            "runtime_state": runtime_state.to_dict(),
            "duration_ms": duration_ms,
        }

    return None

async def run_agent_workflow(
    prompt: str,
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    privacy_mode: Optional[str] = None,
    pre_approved_action: bool = False,
) -> Dict[str, Any]:
    """Main AIRA workflow entry point.

    Analyzes intent, personalizes tone, retrieves only relevant context,
    and coordinates dual-engine execution.
    """
    start_time = time.time()
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    sess_id = session_id or f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_state = get_or_create_session(sess_id, project_id)

    active_privacy = privacy_mode or session_state.privacy_mode
    active_proj_id = project_id or session_state.project_id

    # 0. Pre-Routing Deterministic Dispatch Layer
    # Evaluates unambiguous deterministic utility operations BEFORE routing, health checks, or LLM invocation
    intent = analyze_conversational_intent(prompt, active_project_id=active_proj_id)
    deterministic_result = try_dispatch_deterministic_utility(
        prompt=prompt,
        intent=intent,
        request_id=request_id,
        sess_id=sess_id,
        session_state=session_state,
        user_profile_mgr=_user_profile_mgr,
        policy_engine=_policy_engine,
        active_privacy=active_privacy,
        active_proj_id=active_proj_id,
        start_time=start_time,
    )
    if deterministic_result is not None:
        return deterministic_result

    # 1. Routing & Conversational Intent Analysis
    routing_info = await route_request(
        prompt,
        privacy_mode=active_privacy,
        force_local=(active_privacy == "local_only"),
        active_project_id=active_proj_id
    )
    target_engine = routing_info["target_engine"]
    complexity = routing_info["complexity"]
    selected_model = routing_info["model"]

    # 2. Health & Runtime State Probe
    local_alive = await check_local_health()
    cloud_alive = await check_cloud_health()

    # User profile display name
    user_display_name = _user_profile_mgr.get_user_display_name()

    runtime_state = AiraRuntimeState(
        active_local_model=active_light_model,
        local_model_available=local_alive,
        active_cloud_model=HEAVY_MODEL,
        cloud_model_available=cloud_alive,
        privacy_mode=active_privacy,
        active_project_id=active_proj_id,
        active_session_id=sess_id,
        user_display_name=user_display_name,
        pending_approvals=len(_policy_engine.pending_approvals),
    )

    # Fast offline guardrail: If the target engine is unreachable and no fallback permitted
    if not local_alive and (target_engine == "local" or active_privacy == "local_only"):
        if active_privacy == "local_only" or not cloud_alive:
            err_msg = "Error: The local Ollama model is currently offline and cloud escalation is prohibited by your privacy policy."
            _save_turn(sess_id, prompt, err_msg)
            return {
                "request_id": request_id,
                "model_used": active_light_model,
                "complexity": complexity,
                "intent_category": intent.category,
                "target_engine": "local",
                "tools_triggered": False,
                "executed_tools": [],
                "citations": [],
                "result": err_msg,
                "routing_reason": "Local model offline; cloud fallback disabled.",
                "runtime_state": runtime_state.to_dict(),
                "duration_ms": round((time.time() - start_time) * 1000, 2),
            }

    if not cloud_alive and not local_alive:
        err_msg = "Error: Both local and cloud model engines are currently offline. Please check your network or local Ollama service."
        _save_turn(sess_id, prompt, err_msg)
        return {
            "request_id": request_id,
            "model_used": "None",
            "complexity": complexity,
            "intent_category": intent.category,
            "target_engine": "offline",
            "tools_triggered": False,
            "executed_tools": [],
            "citations": [],
            "result": err_msg,
            "routing_reason": "All model providers unreachable.",
            "runtime_state": runtime_state.to_dict(),
            "duration_ms": round((time.time() - start_time) * 1000, 2),
        }

    # 3. Intent-Aware Context Retrieval (Retrieve ONLY what is relevant)
    profile_summary = _user_profile_mgr.get_profile_prompt_summary(intent.category)

    proj_summary = None
    session_summary = None
    if intent.needs_project_context and active_proj_id:
        proj_summary = _project_mgr.get_project_prompt_summary(active_proj_id)
        session_summary = _session_mgr.get_latest_session_prompt_context(active_proj_id)

    # Ambiguous continuation check:
    # If the user asks to continue but multiple projects exist and none is clearly active
    if intent.category == IntentCategory.CONTINUATION and not active_proj_id:
        all_projs = _project_mgr.list_projects()
        if len(all_projs) > 1:
            proj_names = [f"'{p.name}'" for p in all_projs[:3]]
            clarify_text = f"I'd be glad to pick back up! We have active work across {', '.join(proj_names)}. Which one would you like to continue with?"
            _save_turn(sess_id, prompt, clarify_text)
            return {
                "request_id": request_id,
                "model_used": active_light_model,
                "complexity": "LOW",
                "intent_category": intent.category,
                "target_engine": "local",
                "tools_triggered": False,
                "executed_tools": [],
                "citations": [],
                "result": clarify_text,
                "routing_reason": "Ambiguous continuation: asked for clarification.",
                "runtime_state": runtime_state.to_dict(),
                "duration_ms": round((time.time() - start_time) * 1000, 2),
            }

    # 3.5 Gather Grounded Knowledge across RAG, Web Research, Memory, and Project Context
    knowledge_bundle: Optional[KnowledgeBundle] = None
    if intent.category not in (IntentCategory.GREETING, IntentCategory.CASUAL, IntentCategory.USER_INTRODUCTION):
        knowledge_bundle = await _knowledge_engine.gather_knowledge(
            prompt=prompt,
            project_id=active_proj_id,
            privacy_mode=active_privacy,
            intent=intent,
        )

    # Query semantic memories ONLY if relevant (not for greetings/casual chit-chat)
    matched_memories = []
    if intent.category not in (IntentCategory.GREETING, IntentCategory.CASUAL, IntentCategory.USER_INTRODUCTION):
        prompt_words = prompt.lower().split()
        all_semantic = _repo.get_semantic_memories(project_id=active_proj_id, limit=20)
        matched_memories = [
            f"{m.subject}: {m.content}"
            for m in all_semantic
            if any(w in m.subject.lower() or w in m.content.lower() for w in prompt_words if len(w) > 3)
        ][:3]

    # 4. Dynamic System Prompt Assembly with Multi-Turn Conversation History
    system_prompt = build_aira_system_prompt(
        runtime_state=runtime_state,
        user_profile_summary=profile_summary,
        project_summary=proj_summary,
        session_summary=session_summary,
        relevant_memories=matched_memories,
        tone_guidance=intent.tone_guidance,
        include_project_context=intent.needs_project_context,
        user_display_name=user_display_name,
        grounded_knowledge_context=knowledge_bundle.prompt_context_text if knowledge_bundle else None,
    )

    conv_history = _repo.get_conversation_history(sess_id, limit=20)
    messages = [{"role": "system", "content": system_prompt}]
    for hm in conv_history:
        if hm.role in ("user", "assistant"):
            messages.append({"role": hm.role, "content": hm.content})
    messages.append({"role": "user", "content": prompt})

    # 5. Execution Phase
    executed_tools = []
    citations = []
    approval_needed = False
    pending_approval_details = None

    cur_light_client = get_light_client()
    cur_nebius_client = get_nebius_client()

    # --- Light / Local Route (Gemma via Ollama) ---
    escalate_to_cloud = False
    if target_engine == "local" and local_alive:
        try:
            print(f"🚦 [AIRA Routing] Local Engine: {active_light_model} ({complexity} | {intent.category})")
            response = await cur_light_client.chat.completions.create(
                model=active_light_model,
                messages=messages,
                temperature=0.6 if intent.category == IntentCategory.CREATIVE else 0.4,
            )
            raw_content = response.choices[0].message.content or ""

            # Guardrail: Check if the model hallucinated an irrelevant generic greeting
            def is_canned_greeting(text: str) -> bool:
                t = text.strip().lower()
                markers = [
                    "it's a pleasure to meet you",
                    "pleasure to meet you",
                    "how may i assist you today",
                    "how can i assist you today",
                    "how can i help you today",
                    "i'm aira, your intelligent",
                    "i am aira, your intelligent",
                    "greetings, fellow traveler",
                ]
                return any(m in t for m in markers)

            if intent.category not in (IntentCategory.GREETING, IntentCategory.USER_INTRODUCTION) and (not raw_content.strip() or is_canned_greeting(raw_content)):
                if cloud_alive and active_privacy != "local_only":
                    print(f"⚠️ [AIRA Routing] Local model hallucinated canned greeting for '{prompt}'; escalating to Cloud Engine...")
                    escalate_to_cloud = True
                else:
                    strict_messages = list(messages) + [
                        {"role": "system", "content": "IMPORTANT: Do NOT greet, introduce yourself, or ask how to help. Directly answer the user's question without preamble."}
                    ]
                    retry_resp = await cur_light_client.chat.completions.create(
                        model=active_light_model,
                        messages=strict_messages,
                        temperature=0.3,
                    )
                    raw_content = retry_resp.choices[0].message.content or raw_content

            if not escalate_to_cloud:
                result_text = raw_content.strip() or "I am here to help you."

                # Record turn in persistent history
                _save_turn(sess_id, prompt, result_text)
                session_state.interaction_count += 1

                # Record episodic memory ONLY for meaningful interactions (never for casual greetings)
                if intent.category not in (IntentCategory.GREETING, IntentCategory.CASUAL, IntentCategory.USER_INTRODUCTION) and len(prompt) > 30 and len(result_text) > 40:
                    _repo.add_episodic(
                        EpisodicMemory(
                            session_id=sess_id,
                            project_id=active_proj_id,
                            title=prompt[:60],
                            content=result_text[:300],
                            event_type=intent.category,
                            importance=0.4
                        )
                    )

                # Validate citations against grounded knowledge
                local_citations = []
                if knowledge_bundle:
                    _, valid_cites, _ = knowledge_bundle.validate_answer_citations(result_text)
                    local_citations = list(dict.fromkeys(knowledge_bundle.citations + valid_cites))

                return {
                    "request_id": request_id,
                    "model_used": active_light_model,
                    "complexity": complexity,
                    "intent_category": intent.category,
                    "target_engine": "local",
                    "tools_triggered": False,
                    "executed_tools": [],
                    "citations": local_citations,
                    "sources_used": knowledge_bundle.sources_used if knowledge_bundle else [],
                    "contradictions": knowledge_bundle.contradictions if knowledge_bundle else [],
                    "result": result_text,
                    "routing_reason": routing_info["reason"],
                    "runtime_state": runtime_state.to_dict(),
                    "duration_ms": round((time.time() - start_time) * 1000, 2),
                }
        except Exception as e:
            print(f"⚠️ Local engine error ({e}); attempting cloud escalation fallback if permitted...")
            if active_privacy == "local_only" or not cloud_alive:
                return {
                    "request_id": request_id,
                    "model_used": active_light_model,
                    "complexity": complexity,
                    "intent_category": intent.category,
                    "target_engine": "local",
                    "tools_triggered": False,
                    "result": f"Local model error: {str(e)}. Cloud fallback prohibited by Local-Only privacy mode.",
                    "runtime_state": runtime_state.to_dict(),
                }

    # --- Heavy / Cloud Route (Nemotron via OpenRouter/Nebius) ---
    print(f"🚀 [AIRA Routing] Cloud Engine: {HEAVY_MODEL} ({complexity} | {intent.category})")

    # Select tools: Only include tools if the task requires tools!
    tool_schemas = _tool_registry.get_schemas() if (intent.needs_coding_tools or intent.needs_web_search or complexity == "HEAVY" or intent.category == IntentCategory.DESKTOP_ACTION) else None

    if intent.category == IntentCategory.DESKTOP_ACTION:
        messages.append({
            "role": "system",
            "content": "You have access to desktop tools including desktop_open_application, desktop_system_diagnostics, desktop_list_running_apps. When the user asks to open an app or inspect the system, call the appropriate desktop tool."
        })

    cloud_kwargs: Dict[str, Any] = {
        "model": HEAVY_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}}
    }
    if tool_schemas:
        cloud_kwargs["tools"] = tool_schemas
        cloud_kwargs["tool_choice"] = "auto"

    try:
        response = await cur_nebius_client.chat.completions.create(**cloud_kwargs)
    except Exception as e:
        # Fallback to local model if cloud fails
        if local_alive:
            print(f"⚠️ Cloud engine error ({e}); falling back to Local Gemma...")
            fallback_resp = await cur_light_client.chat.completions.create(
                model=active_light_model,
                messages=messages,
                temperature=0.5,
            )
            fallback_text = fallback_resp.choices[0].message.content or ""
            _save_turn(sess_id, prompt, fallback_text)
            session_state.interaction_count += 1
            return {
                "request_id": request_id,
                "model_used": f"{active_light_model} (Cloud Fallback)",
                "complexity": complexity,
                "intent_category": intent.category,
                "target_engine": "local_fallback",
                "tools_triggered": False,
                "executed_tools": [],
                "citations": [],
                "approval_required": False,
                "pending_approval": None,
                "result": fallback_text,
                "routing_reason": f"Cloud provider unavailable ({str(e)}); gracefully served locally.",
                "runtime_state": runtime_state.to_dict(),
            }
        raise

    message = response.choices[0].message

    # 6. Tool Execution with Security Policy Layer
    if message.tool_calls:
        print(f"🔧 [AIRA Tool Engine] Model requested {len(message.tool_calls)} tool execution(s)")
        messages.append(message)

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            try:
                raw_args = json.loads(tool_call.function.arguments)
            except Exception:
                raw_args = {}

            tool_def = _tool_registry.get_tool(func_name)
            action_type = tool_def.action_type if tool_def else "UNKNOWN"

            # Evaluate with Policy Decision Layer
            decision, risk, reason = _policy_engine.evaluate_action(
                action_type=action_type,
                tool_name=func_name,
                parameters=raw_args,
                request_id=request_id,
                privacy_mode=active_privacy,
                authorized_root=str(BASE_DIR),
                pre_approved=pre_approved_action,
            )

            executed_tools.append({
                "tool": func_name,
                "risk_level": risk,
                "decision": decision,
                "reason": reason,
                "arguments": raw_args,
            })

            if decision == "DENY":
                tool_output = json.dumps({
                    "status": "denied",
                    "policy_decision": "DENY",
                    "reason": reason
                })
            elif decision == "REQUIRE_APPROVAL":
                approval_needed = True
                approval_id = f"appr_{uuid.uuid4().hex[:8]}"
                pending_approval_details = _policy_engine.register_approval_request(
                    approval_id=approval_id,
                    tool_name=func_name,
                    parameters=raw_args,
                    reason=reason,
                    risk_level=risk,
                )
                tool_output = json.dumps({
                    "status": "pending_human_approval",
                    "approval_id": approval_id,
                    "message": f"Action paused: {reason} Awaiting human confirmation."
                })
            else:
                # Allowed: execute tool
                tool_output = _tool_registry.execute(func_name, raw_args)

                # Extract citations if search or RAG tool
                try:
                    out_json = json.loads(tool_output)
                    if "results" in out_json and isinstance(out_json["results"], list):
                        for r in out_json["results"]:
                            if "url" in r:
                                citations.append(f"[{r.get('title', 'Web Source')}]({r.get('url')})")
                            elif "citation" in r:
                                citations.append(r["citation"])
                except Exception:
                    pass

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": func_name,
                "content": tool_output
            })

        # 7. Final Synthesis with Citations
        final_response = await cur_nebius_client.chat.completions.create(
            model=HEAVY_MODEL,
            messages=messages,
            temperature=0.3,
            extra_body={"chat_template_kwargs": {"enable_thinking": True}}
        )
        final_text = final_response.choices[0].message.content or ""

        # Record turn in persistent history
        _save_turn(sess_id, prompt, final_text)
        session_state.interaction_count += 1

        # Save meaningful outcome to episodic memory
        if intent.category not in (IntentCategory.GREETING, IntentCategory.CASUAL, IntentCategory.USER_INTRODUCTION):
            _repo.add_episodic(
                EpisodicMemory(
                    session_id=sess_id,
                    project_id=active_proj_id,
                    title=f"Task: {prompt[:50]}",
                    content=final_text[:400],
                    event_type="tool_execution",
                    importance=0.8
                )
            )

        # Validate citations from tool execution + knowledge bundle
        all_cloud_citations = list(dict.fromkeys(citations + (knowledge_bundle.citations if knowledge_bundle else [])))
        if knowledge_bundle:
            _, valid_cites, _ = knowledge_bundle.validate_answer_citations(final_text)
            all_cloud_citations = list(dict.fromkeys(all_cloud_citations + valid_cites))

        return {
            "request_id": request_id,
            "model_used": HEAVY_MODEL,
            "complexity": complexity,
            "intent_category": intent.category,
            "target_engine": "cloud",
            "tools_triggered": True,
            "executed_tools": executed_tools,
            "citations": all_cloud_citations,
            "sources_used": knowledge_bundle.sources_used if knowledge_bundle else [],
            "contradictions": knowledge_bundle.contradictions if knowledge_bundle else [],
            "result": final_text,
            "routing_reason": routing_info["reason"],
            "approval_required": approval_needed,
            "pending_approval": pending_approval_details,
            "runtime_state": runtime_state.to_dict(),
            "duration_ms": round((time.time() - start_time) * 1000, 2),
        }

    # No tools used
    cloud_answer = message.content or ""
    _save_turn(sess_id, prompt, cloud_answer)
    session_state.interaction_count += 1

    cloud_direct_citations = []
    if knowledge_bundle:
        _, valid_cites, _ = knowledge_bundle.validate_answer_citations(cloud_answer)
        cloud_direct_citations = list(dict.fromkeys(knowledge_bundle.citations + valid_cites))

    return {
        "request_id": request_id,
        "model_used": HEAVY_MODEL,
        "complexity": complexity,
        "intent_category": intent.category,
        "target_engine": "cloud",
        "tools_triggered": False,
        "executed_tools": [],
        "citations": cloud_direct_citations,
        "sources_used": knowledge_bundle.sources_used if knowledge_bundle else [],
        "contradictions": knowledge_bundle.contradictions if knowledge_bundle else [],
        "result": cloud_answer,
        "routing_reason": routing_info["reason"],
        "approval_required": False,
        "runtime_state": runtime_state.to_dict(),
        "duration_ms": round((time.time() - start_time) * 1000, 2),
    }

def get_shared_repository() -> MemoryRepository:
    return _repo

def get_shared_policy_engine() -> PolicyDecisionEngine:
    return _policy_engine

def get_shared_project_manager() -> ProjectContextManager:
    return _project_mgr

def get_shared_user_profile_manager() -> UserProfileManager:
    return _user_profile_mgr

def get_shared_knowledge_engine() -> UnifiedKnowledgeEngine:
    return _knowledge_engine