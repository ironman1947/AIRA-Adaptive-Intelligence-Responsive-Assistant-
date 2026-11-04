"""FastAPI Backend for Project AIRA (Adaptive Intelligence & Responsive Assistant)."""

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger("aira.api")

from src.agent.core import (
    run_agent_workflow,
    get_shared_repository,
    get_shared_policy_engine,
    get_shared_project_manager,
    get_shared_user_profile_manager,
    get_shared_knowledge_engine,
)
from src.agent.identity import AiraRuntimeState, ASSISTANT_NAME, VERSION
from src.agent.router import check_local_health, check_cloud_health, determine_complexity
from src.memory.models import ProjectWorkspace, FeedbackRecord
from src.rag.store import get_rag_store
from src.security.constitution import PRINCIPLES, CONSTITUTION_VERSION
from src.evaluation.feedback import FeedbackService
from src.evaluation.eval_runner import run_benchmark_evaluation
from src.config import AIRA_STORAGE_DIR
from src.voice import get_voice_service, clean_text_for_speech
from src.voice.providers import get_available_macos_voices
from src.voice.live_provider import GeminiLiveVoiceProvider

app = FastAPI(
    title=f"Project {ASSISTANT_NAME} API",
    version=VERSION,
    description="Backend API for AIRA: Personal AI Companion, Coding Coworker, and Intelligent Agent."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

repo = get_shared_repository()
policy_engine = get_shared_policy_engine()
project_mgr = get_shared_project_manager()
profile_mgr = get_shared_user_profile_manager()
rag_store = get_rag_store()
feedback_service = FeedbackService(repo)
voice_service = get_voice_service()
knowledge_engine = get_shared_knowledge_engine()

class AgentRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    privacy_mode: Optional[str] = "standard"  # standard | local_only
    pre_approved_action: bool = False

class CreateConversationRequest(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    user_id: Optional[str] = "default_user"
    metadata: Optional[Dict[str, Any]] = None

class UpdateConversationRequest(BaseModel):
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class AddMessageRequest(BaseModel):
    role: str
    content: str
    engine: Optional[str] = None
    model: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class FeedbackRequest(BaseModel):
    request_id: str
    helpful: bool
    rating: Optional[int] = None
    category: str = "helpful"
    user_explanation: Optional[str] = None
    model_used: Optional[str] = None
    tools_triggered: bool = False
    prompt: Optional[str] = None
    response: Optional[str] = None

class RAGSearchRequest(BaseModel):
    query: str
    top_k: int = 4
    project_id: Optional[str] = None

class ApprovalActionRequest(BaseModel):
    approval_id: str
    approved: bool

class VoiceSynthesizeRequest(BaseModel):
    text: str
    voice_id: Optional[str] = "Samantha"
    rate: Optional[int] = 180
    language: Optional[str] = "en"
    summarize_for_speech: bool = True
    request_id: Optional[str] = None

class ResearchRequest(BaseModel):
    query: str
    privacy_mode: Optional[str] = "standard"
    max_results: int = 4

class VoiceInterruptRequest(BaseModel):
    session_id: Optional[str] = None
    reason: Optional[str] = "barge_in"

# ------------------------------------------------------------------------------
# Health and Runtime State
# ------------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    """Health check endpoint preserving Nebius container ping while returning system diagnostics."""
    local_ok = await check_local_health()
    cloud_ok = await check_cloud_health()
    return {
        "status": "healthy",
        "assistant": ASSISTANT_NAME,
        "version": VERSION,
        "local_engine_online": local_ok,
        "cloud_engine_online": cloud_ok,
        "storage_initialized": True,
    }

@app.get("/api/runtime-state")
async def get_runtime_state():
    local_ok = await check_local_health()
    cloud_ok = await check_cloud_health()
    state = AiraRuntimeState(
        local_model_available=local_ok,
        cloud_model_available=cloud_ok,
        pending_approvals=len(policy_engine.pending_approvals),
    )
    return state.to_dict()

# ------------------------------------------------------------------------------
# Main Chat & Persistent Conversation Management
# ------------------------------------------------------------------------------
@app.post("/api/conversations")
async def create_conversation_endpoint(req: Optional[CreateConversationRequest] = None):
    """Creates a new persistent conversation."""
    req_data = req or CreateConversationRequest()
    conv = repo.create_conversation(
        conversation_id=req_data.id,
        title=req_data.title,
        user_id=req_data.user_id or "default_user",
        metadata=req_data.metadata or {},
    )
    return conv.model_dump()

@app.get("/api/conversations")
async def list_conversations_endpoint(
    user_id: str = "default_user",
    search: Optional[str] = None,
    limit: int = 100,
):
    """Retrieves all conversations sorted by most recently updated."""
    convs = repo.list_conversations(user_id=user_id, search=search, limit=limit)
    return [c.model_dump() for c in convs]

@app.get("/api/conversations/{conversation_id}")
async def get_conversation_endpoint(conversation_id: str):
    """Retrieves conversation details along with its chronological messages."""
    conv = repo.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = repo.get_messages(conversation_id, limit=200)
    data = conv.model_dump()
    data["messages"] = [m.model_dump() for m in messages]
    return data

@app.patch("/api/conversations/{conversation_id}")
async def update_conversation_endpoint(conversation_id: str, req: UpdateConversationRequest):
    """Renames a conversation or updates its metadata."""
    conv = repo.update_conversation(
        conversation_id=conversation_id,
        title=req.title,
        metadata=req.metadata,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv.model_dump()

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str):
    """Deletes a conversation and cascades to its messages."""
    success = repo.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "conversation_id": conversation_id}

@app.post("/api/conversations/{conversation_id}/messages")
async def add_message_endpoint(conversation_id: str, req: AddMessageRequest):
    """Appends a single message to a conversation."""
    msg = repo.add_message(
        conversation_id=conversation_id,
        role=req.role,
        content=req.content,
        engine=req.engine,
        model=req.model,
        metadata=req.metadata or {},
    )
    return msg.model_dump()

@app.post("/api/chat")
async def chat_endpoint(request: AgentRequest):
    """Primary chat entry point for AIRA with reliable conversation persistence."""
    try:
        sess_id = request.session_id
        if sess_id:
            conv = repo.get_conversation(sess_id)
            if not conv:
                from src.memory.repository import generate_conversation_title
                repo.create_conversation(
                    conversation_id=sess_id,
                    title=generate_conversation_title(request.prompt),
                    metadata={"project_id": request.project_id} if request.project_id else {},
                )

        response = await run_agent_workflow(
            prompt=request.prompt,
            session_id=sess_id,
            project_id=request.project_id,
            privacy_mode=request.privacy_mode,
            pre_approved_action=request.pre_approved_action,
        )

        actual_sess_id = response.get("runtime_state", {}).get("active_session_id") or sess_id
        response["conversation_id"] = actual_sess_id
        response["session_id"] = actual_sess_id
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history/{session_id}")
async def get_chat_history(session_id: str, limit: int = 50):
    """Retrieves chronological conversation history for a session."""
    messages = repo.get_conversation_history(session_id, limit=limit)
    return [m.model_dump() for m in messages]

@app.delete("/api/history/{session_id}")
async def clear_chat_history(session_id: str):
    """Clears conversation history for a session."""
    repo.clear_conversation_history(session_id)
    return {"status": "cleared", "session_id": session_id}

@app.get("/api/user-profile/name")
async def get_user_display_name():
    """Retrieves the user's explicit display name."""
    name = profile_mgr.get_user_display_name()
    return {"user_display_name": name, "is_known": bool(name)}

class SetUserNameRequest(BaseModel):
    name: str

@app.post("/api/user-profile/name")
async def set_user_display_name_endpoint(req: SetUserNameRequest):
    """Explicitly sets or corrects the user's display name."""
    cleaned = profile_mgr.set_user_display_name(req.name)
    return {"status": "saved", "user_display_name": cleaned}

@app.delete("/api/user-profile/name")
async def clear_user_display_name_endpoint():
    """Clears the user's display name."""
    profile_mgr.clear_user_display_name()
    return {"status": "cleared"}

# ------------------------------------------------------------------------------
# User Feedback and Evaluation
# ------------------------------------------------------------------------------
@app.post("/api/feedback")
async def submit_feedback(fb: FeedbackRequest):
    record = feedback_service.submit_feedback(
        request_id=fb.request_id,
        helpful=fb.helpful,
        rating=fb.rating,
        category=fb.category,
        user_explanation=fb.user_explanation,
        model_used=fb.model_used,
        tools_triggered=fb.tools_triggered,
        prompt=fb.prompt,
        response=fb.response,
    )
    return {"status": "recorded", "feedback_id": record.id}

@app.get("/api/feedback/metrics")
async def get_feedback_metrics():
    return feedback_service.get_feedback_metrics()

@app.post("/api/evaluation/run")
async def run_evaluation():
    report = await run_benchmark_evaluation(router_func=determine_complexity)
    return report

# ------------------------------------------------------------------------------
# Project Workspace Management
# ------------------------------------------------------------------------------
@app.get("/api/projects")
async def list_projects():
    return project_mgr.list_projects()

@app.post("/api/projects")
async def create_or_update_project(proj: ProjectWorkspace):
    saved = project_mgr.save_project(proj)
    return saved

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    success = repo.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}

# ------------------------------------------------------------------------------
# Memory and Personalization Management
# ------------------------------------------------------------------------------
@app.get("/api/memory")
async def get_memories(category: str = "all", project_id: Optional[str] = None):
    if category == "episodic":
        return repo.get_episodic_memories(project_id=project_id)
    elif category == "semantic":
        return repo.get_semantic_memories(project_id=project_id)
    elif category == "procedural":
        return repo.get_procedural_memories(project_id=project_id)
    elif category == "profile":
        return profile_mgr.get_profile_dict()
    elif category == "preferences":
        return repo.list_preferences()
    elif category == "export":
        return repo.export_all_memories()
    else:
        return repo.export_all_memories()

@app.delete("/api/memory/{category}/{item_id}")
async def delete_memory_item(category: str, item_id: int):
    if category == "episodic":
        ok = repo.delete_episodic(item_id)
    elif category == "semantic":
        ok = repo.delete_semantic(item_id)
    elif category == "procedural":
        ok = repo.delete_procedural(item_id)
    elif category == "preferences":
        ok = repo.delete_preference(item_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid memory category")

    if not ok:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return {"status": "deleted", "category": category, "id": item_id}

@app.post("/api/preferences/{pref_id}/approve")
async def approve_preference(pref_id: int):
    ok = repo.set_preference_approval(pref_id, approved=True)
    if not ok:
        raise HTTPException(status_code=404, detail="Preference not found")
    return {"status": "approved", "id": pref_id}

@app.post("/api/preferences/{pref_id}/reject")
async def reject_preference(pref_id: int):
    ok = repo.delete_preference(pref_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Preference not found")
    return {"status": "rejected_and_deleted", "id": pref_id}

# ------------------------------------------------------------------------------
# RAG Document Management & Search
# ------------------------------------------------------------------------------
@app.get("/api/rag/documents")
async def list_rag_documents(project_id: Optional[str] = None):
    return rag_store.list_documents(project_id=project_id)

@app.post("/api/rag/upload")
async def upload_document(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    privacy_level: str = Form("standard"),
):
    upload_dir = Path(AIRA_STORAGE_DIR) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / file.filename

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    try:
        res = rag_store.index_document(
            file_path=str(save_path),
            project_id=project_id,
            privacy_level=privacy_level
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to index document: {str(e)}")

@app.post("/api/rag/search")
async def search_rag(req: RAGSearchRequest):
    results = rag_store.search(req.query, top_k=req.top_k, project_id=req.project_id)
    return {"query": req.query, "count": len(results), "results": results}

@app.delete("/api/rag/documents/{doc_id}")
async def delete_rag_document(doc_id: str):
    ok = rag_store.delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": doc_id}

# ------------------------------------------------------------------------------
# Operational Constitution and Approvals
# ------------------------------------------------------------------------------
@app.get("/api/constitution")
async def get_constitution():
    return {
        "version": CONSTITUTION_VERSION,
        "principles": PRINCIPLES,
        "active_safeguards": [
            "SSRF IP filter on external HTTP fetches",
            "Path traversal prevention outside workspace",
            "Human confirmation required for high-risk modifications and tests",
            "Credential redaction in audit logs",
            "Local-only privacy mode enforcement"
        ]
    }

@app.get("/api/audit-logs")
async def get_audit_logs(limit: int = 50):
    return repo.list_audit_logs(limit=limit)

@app.get("/api/approvals")
async def get_pending_approvals():
    return list(policy_engine.pending_approvals.values())

@app.post("/api/approvals/resolve")
async def resolve_approval(req: ApprovalActionRequest):
    res = policy_engine.resolve_approval(req.approval_id, req.approved)
    if not res:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return res

# ------------------------------------------------------------------------------
# Voice Intelligence Subsystem Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/voice/config")
async def get_voice_config():
    """Returns available voice synthesis voices, languages, and provider status."""
    from src.voice.providers import ElevenLabsTextToSpeechProvider
    is_eleven = isinstance(voice_service.tts, ElevenLabsTextToSpeechProvider) and bool(voice_service.tts.api_key)

    voices = []
    if is_eleven:
        voices.extend([
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah (ElevenLabs Neural - Feminine Conversational)", "language": "en-US", "gender": "female", "provider": "elevenlabs"},
            {"id": "cgSgspJ2msm6clMCkdW9", "name": "Jessica (ElevenLabs Neural - Bright Conversational)", "language": "en-US", "gender": "female", "provider": "elevenlabs"},
            {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (ElevenLabs Neural - Calm Professional)", "language": "en-US", "gender": "female", "provider": "elevenlabs"},
        ])
    voices.extend(get_available_macos_voices())

    return {
        "available_voices": voices,
        "default_voice": "EXAVITQu4vr4xnSDxMaL" if is_eleven else "Samantha",
        "current_provider": "elevenlabs" if is_eleven else "macos",
        "supported_languages": [
            {"code": "en", "name": "English", "locale": "en-US"},
            {"code": "hi", "name": "Hindi (हिंदी)", "locale": "hi-IN"},
            {"code": "mr", "name": "Marathi (मराठी)", "locale": "mr-IN"},
            {"code": "auto", "name": "Auto Detect", "locale": None},
        ],
        "local_asr_ready": voice_service.local_stt.is_ready(),
        "tts_available": True,
        "live_mode_available": GeminiLiveVoiceProvider.is_available(),
        "live_default_model": GeminiLiveVoiceProvider.DEFAULT_MODEL,
        "live_default_voice": GeminiLiveVoiceProvider.DEFAULT_VOICE,
        "active_voice_mode": os.getenv("AIRA_VOICE_MODE", "live" if GeminiLiveVoiceProvider.is_available() else "chained"),
    }

@app.post("/api/voice/transcribe")
async def transcribe_voice(
    file: UploadFile = File(...),
    language: Optional[str] = Form("en"),
    privacy_mode: Optional[str] = Form("standard"),
):
    """Transcribes an uploaded audio file (WAV, WebM, MP3, OGG) to text.
    
    Respects privacy_mode (if local_only, strictly uses local offline Faster-Whisper).
    Returns transcript, confidence, language, duration, and trace diagnostics.
    """
    import uuid
    trace_id = str(uuid.uuid4())[:8]

    content = await file.read()
    if not content or len(content) < 12:
        logger.warning(f"[{trace_id}] Voice transcribe rejected: empty audio payload")
        raise HTTPException(status_code=400, detail="Empty audio payload received")

    # Max 25 MB payload safeguard
    if len(content) > 25 * 1024 * 1024:
        logger.warning(f"[{trace_id}] Voice transcribe rejected: payload too large ({len(content)} bytes)")
        raise HTTPException(status_code=413, detail="Audio file exceeds 25 MB limit")

    lang_param = None if language in ("auto", "", None) else language
    content_type = file.content_type or "application/octet-stream"
    logger.info(f"[{trace_id}] Audio transcription request: {len(content)} bytes, type={content_type}, lang={lang_param}, privacy={privacy_mode}")

    try:
        result = await voice_service.transcribe_audio_bytes(
            audio_bytes=content,
            language=lang_param,
            privacy_mode=privacy_mode or "standard",
        )
        logger.info(f"[{trace_id}] Audio transcription completed: duration={result.duration_ms}ms, lang={result.language}, success={bool(result.text.strip())}")

        return {
            "text": result.text,
            "confidence": result.confidence,
            "language_detected": result.language,
            "duration_ms": result.duration_ms,
            "provider_used": "faster-whisper-local" if privacy_mode == "local_only" else "google-speech-remote",
            "success": bool(result.text.strip()),
            "trace_id": trace_id,
            "sample_count": getattr(result, "sample_count", 0),
            "diagnostics": getattr(result, "diagnostics", None),
        }
    except ValueError as ve:
        logger.warning(f"[{trace_id}] Invalid audio payload: {ve}")
        raise HTTPException(status_code=400, detail=f"Invalid audio format or corrupt container: {str(ve)}")
    except RuntimeError as re:
        logger.error(f"[{trace_id}] Transcription engine runtime error: {re}")
        raise HTTPException(status_code=502, detail=f"Speech recognition service error: {str(re)}")
    except Exception as e:
        logger.error(f"[{trace_id}] Unexpected audio transcription failure: {e}")
        raise HTTPException(status_code=500, detail=f"Voice processing failure: {str(e)}")

@app.post("/api/voice/synthesize")
async def synthesize_voice(req: VoiceSynthesizeRequest):
    """Synthesizes text into spoken audio WAV.
    
    Applies conversational text cleanup to avoid reading markdown tables or code blocks aloud.
    """
    import uuid
    trace_id = str(uuid.uuid4())[:8]

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    text_to_speak = clean_text_for_speech(req.text) if req.summarize_for_speech else req.text
    if not text_to_speak:
        text_to_speak = "I have prepared the response for you."

    try:
        audio_chunk = await voice_service.synthesize_speech(
            text=text_to_speak,
            voice_style=req.voice_id or "Samantha",
            privacy_mode="standard",
        )

        if not audio_chunk.data or len(audio_chunk.data) < 44:
            logger.error(f"[{trace_id}] TTS synthesis produced empty audio data")
            raise HTTPException(status_code=500, detail="TTS synthesis failed to produce audio data")

        resp_headers = {
            "X-Trace-ID": trace_id,
            "X-Spoken-Text": text_to_speak[:150].replace("\n", " "),
            "Content-Disposition": "inline; filename=aira_speech.wav",
        }
        if req.request_id:
            resp_headers["X-Response-ID"] = req.request_id

        provider_used = getattr(voice_service.tts, "last_provider_used", "macos")
        resp_headers["X-TTS-Provider"] = provider_used
        resp_headers["X-Generation-Status"] = "success" if provider_used == "elevenlabs" else "fallback"
        resp_headers["X-Audio-Decoding"] = "valid_pcm16"
        resp_headers["X-Voice-ID"] = getattr(voice_service.tts, "voice_id", "EXAVITQu4vr4xnSDxMaL")
        resp_headers["X-Model-ID"] = getattr(voice_service.tts, "model_id", "eleven_v4_turbo")

        if provider_used == "macos_say_fallback":
            fallback_reason = getattr(voice_service.tts, "last_metrics", {}).get("fallback_reason") or "Neural synthesis failed"
            resp_headers["X-Fallback-Warning"] = f"ElevenLabs neural TTS unavailable ({fallback_reason}); fell back to macOS speech engine."

        metrics = getattr(voice_service.tts, "last_metrics", {})
        if "ttfb_ms" in metrics:
            resp_headers["X-TTFB-Ms"] = str(metrics["ttfb_ms"])
        if "duration_ms" in metrics:
            resp_headers["X-Total-Duration-Ms"] = str(metrics["duration_ms"])

        return Response(
            content=audio_chunk.data,
            media_type="audio/wav",
            headers=resp_headers
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{trace_id}] Speech synthesis error: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis error: {str(e)}")

@app.post("/api/voice/stop")
async def stop_voice_playback():
    """Immediately stops active speech synthesis and cancels background say processes."""
    voice_service.stop_speech()
    return {"status": "stopped", "interrupted": True}

@app.post("/api/voice/interrupt")
async def interrupt_voice_playback(req: Optional[VoiceInterruptRequest] = None):
    """Immediately halts active speech synthesis and signals interruption."""
    voice_service.stop_speech()
    sess = req.session_id if req else None
    return {"status": "interrupted", "success": True, "session_id": sess}

# ------------------------------------------------------------------------------
# Grounded Knowledge and Research Endpoints
# ------------------------------------------------------------------------------
@app.post("/api/knowledge/research")
async def research_topic(req: ResearchRequest):
    """Executes safe, multi-query internet research with contradiction detection."""
    if req.privacy_mode == "local_only":
        raise HTTPException(status_code=403, detail="Internet research is prohibited in Local-Only privacy mode.")

    results, contradictions = knowledge_engine.research_engine.multi_query_research(
        queries=[req.query],
        max_per_query=req.max_results,
        fetch_pages_per_query=1,
    )
    return {
        "query": req.query,
        "results_count": len(results),
        "results": results,
        "contradictions": contradictions,
    }

# ------------------------------------------------------------------------------
# Controlled Desktop Subsystem Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/desktop/status")
async def get_desktop_status():
    """Returns desktop service status, authorized workspaces, and pending modification plans."""
    from src.desktop.service import get_desktop_service
    desktop_svc = get_desktop_service()
    diag = desktop_svc.get_system_diagnostics().get("diagnostics", {})
    return {
        "authorized_roots": [str(r) for r in desktop_svc.authorized_roots],
        "approved_applications": list(sorted(set(desktop_svc.APPROVED_APPLICATIONS.values()))),
        "pending_plans": [p.to_dict() for p in desktop_svc.active_plans.values() if p.status == "pending_approval"],
        "diagnostics": diag,
    }

@app.post("/api/desktop/approve")
async def approve_desktop_plan(req: ApprovalActionRequest):
    """Explicitly approves or rejects a pending modification plan."""
    from src.desktop.service import get_desktop_service
    desktop_svc = get_desktop_service()
    if req.approved:
        policy_engine.resolve_approval(req.approval_id, approved=True)
        res = desktop_svc.execute_approved_plan(req.approval_id)
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("error", "Plan execution failed"))
        return res
    else:
        res = desktop_svc.reject_plan(req.approval_id, reason="Declined by user")
        return res