"""PROJECT AIRA — Adaptive Intelligence & Responsive Assistant

Premium Personal AI Workspace & Multi-Agent Interface.
"""

import os
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv
import requests
import streamlit as st

# ------------------------------------------------------------------------------
# Environment & Configuration Loading
# ------------------------------------------------------------------------------
# Explicitly load .env from project root
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

def get_backend_url() -> str:
    """Resolves backend API URL from environment, Streamlit secrets, or defaults."""
    url = os.getenv("AIRA_BACKEND_URL", "").strip()
    if url:
        return url.rstrip("/")
    try:
        if hasattr(st, "secrets") and "AIRA_BACKEND_URL" in st.secrets:
            sec_url = str(st.secrets["AIRA_BACKEND_URL"]).strip()
            if sec_url:
                return sec_url.rstrip("/")
    except Exception:
        pass
    host = os.getenv("HOST", "127.0.0.1").strip()
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = os.getenv("PORT", "8080").strip()
    return f"http://{host}:{port}"

def get_configured_token() -> str:
    """Safely retrieves the configured AIRA_API_TOKEN with multi-source fallback."""
    token = os.getenv("AIRA_API_TOKEN", "").strip()
    if token:
        return token
    try:
        if hasattr(st, "secrets") and "AIRA_API_TOKEN" in st.secrets:
            sec_token = str(st.secrets["AIRA_API_TOKEN"]).strip()
            if sec_token:
                return sec_token
    except Exception:
        pass
    try:
        from src.config import AIRA_API_TOKEN as CONFIG_TOKEN
        if CONFIG_TOKEN and str(CONFIG_TOKEN).strip():
            return str(CONFIG_TOKEN).strip()
    except Exception:
        pass
    return ""

BACKEND_URL = get_backend_url()
AIRA_API_TOKEN = get_configured_token()

# ------------------------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="AIRA — Personal AI Workspace",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------------------
# Custom Premium Styling (Midnight Navy / Electric Cyan / Restrained Violet)
# ------------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
/* Font and Base Smoothing */
html, body, [class*="css"] {
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

/* Hide Default Streamlit Header Decoration for Clean SaaS Aesthetic */
header[data-testid="stHeader"] {
    background: transparent;
}

/* Luminous Orb Visual */
.aira-orb-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2.0rem 1rem 1.2rem 1rem;
    text-align: center;
}

.aira-orb {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #00F0FF 0%, #0070F3 45%, #8B5CF6 80%, #070A12 100%);
    box-shadow: 0 0 30px rgba(0, 240, 255, 0.4), 0 0 60px rgba(139, 92, 246, 0.2);
    animation: aira-pulse 4.5s ease-in-out infinite alternate;
    position: relative;
    margin-bottom: 1.0rem;
}

.aira-orb::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 98px;
    height: 98px;
    border-radius: 50%;
    border: 1px dashed rgba(0, 240, 255, 0.35);
    animation: aira-ring-spin 20s linear infinite;
}

@keyframes aira-pulse {
    0% {
        transform: scale(0.96);
        box-shadow: 0 0 20px rgba(0, 240, 255, 0.3), 0 0 40px rgba(139, 92, 246, 0.15);
    }
    100% {
        transform: scale(1.03);
        box-shadow: 0 0 35px rgba(0, 240, 255, 0.55), 0 0 70px rgba(139, 92, 246, 0.3);
    }
}

@keyframes aira-ring-spin {
    0% { transform: translate(-50%, -50%) rotate(0deg); }
    100% { transform: translate(-50%, -50%) rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
    .aira-orb, .aira-orb::after {
        animation: none;
    }
}

/* Sidebar Brand Header */
.aira-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0.6rem 0.2rem 1.0rem 0.2rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    margin-bottom: 0.8rem;
}

.aira-mini-orb {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #00F0FF 0%, #0070F3 50%, #8B5CF6 100%);
    box-shadow: 0 0 14px rgba(0, 240, 255, 0.5);
    flex-shrink: 0;
}

.aira-sidebar-title {
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: #F8FAFC;
    line-height: 1.1;
}

.aira-sidebar-sub {
    font-size: 0.72rem;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 500;
}

/* Workspace Header Card */
.aira-workspace-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.8rem 0;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.aira-workspace-title {
    font-size: 1.30rem;
    font-weight: 700;
    color: #F1F5F9;
    letter-spacing: -0.01em;
}

.aira-workspace-subtitle {
    font-size: 0.82rem;
    color: #94A3B8;
    margin-top: 2px;
}

/* Badges */
.aira-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    border-radius: 12px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    background: rgba(255, 255, 255, 0.06);
    color: #CBD5E1;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

.aira-badge-cyan {
    background: rgba(0, 240, 255, 0.12);
    color: #00F0FF;
    border: 1px solid rgba(0, 240, 255, 0.3);
}

.aira-badge-green {
    background: rgba(16, 185, 129, 0.12);
    color: #34D399;
    border: 1px solid rgba(16, 185, 129, 0.3);
}

.aira-badge-amber {
    background: rgba(245, 158, 11, 0.12);
    color: #FBBF24;
    border: 1px solid rgba(245, 158, 11, 0.3);
}

.aira-badge-violet {
    background: rgba(139, 92, 246, 0.12);
    color: #A78BFA;
    border: 1px solid rgba(139, 92, 246, 0.3);
}

/* Conversation Item in Sidebar */
.conv-group-label {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #64748B;
    margin: 0.8rem 0 0.3rem 0;
}

/* Citation Card */
.aira-citation-card {
    background: #0F1626;
    border-left: 3px solid #00F0FF;
    border-radius: 4px;
    padding: 8px 12px;
    margin: 6px 0;
    font-size: 0.85rem;
}
</style>
"""

st.html(CUSTOM_CSS)

# ------------------------------------------------------------------------------
# API Helpers
# ------------------------------------------------------------------------------
def get_auth_headers(extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Generates server-side Authorization headers for backend requests."""
    headers = {}
    token = get_configured_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    return headers

def api_get(endpoint: str, default=None, timeout: float = 10.0):
    """Executes an authenticated GET request with null-safe error recovery."""
    try:
        resp = requests.get(f"{BACKEND_URL}{endpoint}", headers=get_auth_headers(), timeout=timeout)
        if resp.status_code == 200:
            if "api_auth_error" in st.session_state:
                st.session_state.pop("api_auth_error", None)
            return resp.json()
        elif resp.status_code == 401:
            st.session_state["api_auth_error"] = (
                "Backend authentication failed (401 Unauthorized). "
                "Verify that AIRA_API_TOKEN is properly configured in your .env file."
            )
        elif resp.status_code == 404:
            return default
    except Exception as e:
        pass
    return default

def api_post(endpoint: str, payload: dict, timeout: float = 60.0):
    """Executes an authenticated POST request with error and status tracking."""
    try:
        resp = requests.post(f"{BACKEND_URL}{endpoint}", json=payload, headers=get_auth_headers(), timeout=timeout)
        if resp.status_code == 401:
            st.session_state["api_auth_error"] = (
                "Backend authentication failed (401 Unauthorized). "
                "Verify that AIRA_API_TOKEN is properly configured in your .env file."
            )
        elif resp.status_code == 200 and "api_auth_error" in st.session_state:
            st.session_state.pop("api_auth_error", None)
        try:
            body = resp.json()
        except Exception:
            body = {"detail": resp.text}
        return resp.status_code, body
    except Exception as e:
        return 500, {"error": str(e)}

def api_patch(endpoint: str, payload: dict, timeout: float = 10.0):
    """Executes an authenticated PATCH request with error and status tracking."""
    try:
        resp = requests.patch(f"{BACKEND_URL}{endpoint}", json=payload, headers=get_auth_headers(), timeout=timeout)
        if resp.status_code == 401:
            st.session_state["api_auth_error"] = (
                "Backend authentication failed (401 Unauthorized). "
                "Verify that AIRA_API_TOKEN is properly configured in your .env file."
            )
        elif resp.status_code == 200 and "api_auth_error" in st.session_state:
            st.session_state.pop("api_auth_error", None)
        try:
            body = resp.json()
        except Exception:
            body = {"detail": resp.text}
        return resp.status_code, body
    except Exception as e:
        return 500, {"error": str(e)}

def api_delete(endpoint: str, timeout: float = 10.0):
    """Executes an authenticated DELETE request with error and status tracking."""
    try:
        resp = requests.delete(f"{BACKEND_URL}{endpoint}", headers=get_auth_headers(), timeout=timeout)
        if resp.status_code == 401:
            st.session_state["api_auth_error"] = (
                "Backend authentication failed (401 Unauthorized). "
                "Verify that AIRA_API_TOKEN is properly configured in your .env file."
            )
        elif resp.status_code == 200 and "api_auth_error" in st.session_state:
            st.session_state.pop("api_auth_error", None)
        try:
            body = resp.json()
        except Exception:
            body = {"detail": resp.text}
        return resp.status_code, body
    except Exception as e:
        return 500, {"error": str(e)}

def api_voice_stop():
    """Cancels active speech output and stops macOS say processes immediately."""
    try:
        requests.post(f"{BACKEND_URL}/api/voice/stop", headers=get_auth_headers(), timeout=2.0)
    except Exception:
        pass

def api_transcribe(
    audio_bytes: bytes,
    language: str = "auto",
    privacy_mode: str = "standard",
    mime_type: str = "audio/wav",
    filename: str = "recording.wav"
) -> Dict[str, Any]:
    """Uploads audio bytes to backend STT engine, preserving container format and local privacy mode."""
    try:
        files = {"file": (filename, audio_bytes, mime_type)}
        data = {"language": language, "privacy_mode": privacy_mode}
        resp = requests.post(f"{BACKEND_URL}/api/voice/transcribe", files=files, data=data, headers=get_auth_headers(), timeout=35.0)
        if resp.status_code == 200:
            return resp.json()
        err_msg = "Transcription error."
        try:
            err_msg = resp.json().get("detail", resp.text)
        except Exception:
            err_msg = resp.text
        return {"success": False, "error": err_msg, "text": ""}
    except Exception as e:
        return {"success": False, "error": str(e), "text": ""}

def api_synthesize(text: str, voice_id: Optional[str] = None, language: str = "en", request_id: Optional[str] = None) -> Optional[bytes]:
    """Fetches synthesized WAV speech audio from backend TTS engine."""
    try:
        payload = {
            "text": text,
            "voice_id": voice_id or st.session_state.get("selected_voice", "EXAVITQu4vr4xnSDxMaL"),
            "language": language,
            "summarize_for_speech": True,
            "request_id": request_id,
        }
        resp = requests.post(f"{BACKEND_URL}/api/voice/synthesize", json=payload, headers=get_auth_headers(), timeout=25.0)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print(f"TTS synthesis API error: {e}")
    return None

from src.ui.formatting import (
    resolve_engine_and_model_badge as _format_badge,
    group_conversations_by_date,
)

def resolve_engine_and_model_badge(msg: Dict[str, Any]) -> str:
    """Safely extracts engine and model display labels from message metadata.

    Handles missing keys, None values, and legacy formats gracefully without raising AttributeError.
    """
    show_debug = False
    try:
        show_debug = bool(st.session_state.get("show_debug_traces", False))
    except Exception:
        show_debug = False
    return _format_badge(msg, show_debug_traces=show_debug)


# ------------------------------------------------------------------------------
# Persistent Conversation & Session State Initialization
# ------------------------------------------------------------------------------
url_cid = st.query_params.get("cid")

if "conversation_id" not in st.session_state:
    if url_cid:
        st.session_state.conversation_id = url_cid
    else:
        recent = api_get("/api/conversations?limit=1", [])
        if recent and isinstance(recent, list) and len(recent) > 0 and recent[0].get("id"):
            st.session_state.conversation_id = recent[0]["id"]
            st.query_params["cid"] = st.session_state.conversation_id
        else:
            code, created = api_post("/api/conversations", {"title": "New Conversation"})
            new_id = (created.get("id") if (code == 200 and isinstance(created, dict)) else None) or f"conv_{int(time.time())}"
            st.session_state.conversation_id = new_id
            st.query_params["cid"] = new_id
elif url_cid and url_cid != st.session_state.conversation_id:
    st.session_state.conversation_id = url_cid

# Ensure URL always tracks active conversation
st.query_params["cid"] = st.session_state.conversation_id

# Load Messages from Backend Database on Conversation Change
if st.session_state.get("last_loaded_conv_id") != st.session_state.conversation_id:
    conv_data = api_get(f"/api/conversations/{st.session_state.conversation_id}")
    if conv_data and isinstance(conv_data, dict) and "messages" in conv_data:
        st.session_state.messages = conv_data["messages"]
        st.session_state.current_conv_title = conv_data.get("title", "New Conversation")
        st.session_state.last_loaded_conv_id = st.session_state.conversation_id
    else:
        # If requested conversation was not found on backend (e.g. invalid ?cid=), fallback gracefully to latest
        recent = api_get("/api/conversations?limit=1", [])
        if recent and isinstance(recent, list) and len(recent) > 0 and recent[0].get("id") and recent[0]["id"] != st.session_state.conversation_id:
            fallback_cid = recent[0]["id"]
            fallback_data = api_get(f"/api/conversations/{fallback_cid}")
            if fallback_data and isinstance(fallback_data, dict) and "messages" in fallback_data:
                st.session_state.conversation_id = fallback_cid
                st.query_params["cid"] = fallback_cid
                st.session_state.messages = fallback_data["messages"]
                st.session_state.current_conv_title = fallback_data.get("title", "New Conversation")
                st.session_state.last_loaded_conv_id = fallback_cid
            else:
                st.session_state.messages = []
                st.session_state.current_conv_title = "New Conversation"
                st.session_state.last_loaded_conv_id = fallback_cid
        else:
            st.session_state.messages = []
            st.session_state.current_conv_title = "New Conversation"
            st.session_state.last_loaded_conv_id = st.session_state.conversation_id

if "active_section" not in st.session_state:
    st.session_state.active_section = "Conversation"

if "active_project" not in st.session_state:
    st.session_state.active_project = None

if "privacy_mode" not in st.session_state:
    st.session_state.privacy_mode = "standard"  # "standard" | "local_only"

if "show_debug_traces" not in st.session_state:
    st.session_state.show_debug_traces = False

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

if "rag_search_results" not in st.session_state:
    st.session_state.rag_search_results = None

if "voice_output_enabled" not in st.session_state:
    st.session_state.voice_output_enabled = True

if "selected_voice" not in st.session_state:
    st.session_state.selected_voice = "EXAVITQu4vr4xnSDxMaL"

if "selected_language" not in st.session_state:
    st.session_state.selected_language = "auto"

if "chat_draft" not in st.session_state:
    st.session_state.chat_draft = ""

if "dictation_active" not in st.session_state:
    st.session_state.dictation_active = False

if "wake_word_enabled" not in st.session_state:
    st.session_state.wake_word_enabled = False

if "wake_word_state" not in st.session_state:
    st.session_state.wake_word_state = "wake_word_disabled"

if "audio_cache_by_req_id" not in st.session_state:
    st.session_state.audio_cache_by_req_id = {}

if "last_processed_audio_bytes_hash" not in st.session_state:
    st.session_state.last_processed_audio_bytes_hash = None

if "last_error_prompt" not in st.session_state:
    st.session_state.last_error_prompt = None

# Cached / Live Data Fetching
health_data = api_get("/health", {})
is_healthy = health_data.get("status") == "healthy"
local_engine_online = health_data.get("local_engine_online", False)
cloud_engine_online = health_data.get("cloud_engine_online", False)

user_info = api_get("/api/user-profile/name", {})
user_display_name = user_info.get("user_display_name")

# ------------------------------------------------------------------------------
# SIDEBAR: Branding, New Chat, Search, History, Workspaces, and Status
# ------------------------------------------------------------------------------
with st.sidebar:
    # 0. Authentication Status Check
    if st.session_state.get("api_auth_error"):
        st.error(st.session_state["api_auth_error"], icon=":material/security:")
    elif not get_configured_token():
        st.warning("⚠️ AIRA_API_TOKEN is not configured in .env.", icon=":material/lock:")

    # 1. AIRA Logo and Branding
    st.html("""
    <div class="aira-sidebar-brand">
        <div class="aira-mini-orb"></div>
        <div>
            <div class="aira-sidebar-title">AIRA</div>
            <div class="aira-sidebar-sub">Adaptive Intelligence Workspace</div>
        </div>
    </div>
    """)

    # 2. New Chat Button
    if st.button("➕  New Chat", width="stretch", type="primary", key="btn_sidebar_new_chat"):
        st_code, new_c = api_post("/api/conversations", {"title": "New Conversation"})
        if st_code == 200:
            st.session_state.conversation_id = new_c["id"]
            st.query_params["cid"] = new_c["id"]
            st.session_state.messages = []
            st.session_state.current_conv_title = "New Conversation"
            st.session_state.last_loaded_conv_id = new_c["id"]
            st.session_state.active_section = "Conversation"
            st.session_state.pending_prompt = None
            st.rerun()

    # 3. Search Conversations
    conv_search_query = st.text_input(
        "Search conversations...",
        placeholder="🔍 Search history...",
        key="sidebar_search_conversations",
        label_visibility="collapsed",
    )

    # 4. Conversation History Grouped
    search_param = str(conv_search_query or "").strip()
    all_convs = api_get(f"/api/conversations?search={search_param}", [])
    date_groups = group_conversations_by_date(all_convs)

    with st.container(height=260):
        total_found = sum(len(items) for items in date_groups.values())
        if total_found == 0:
            st.caption("No conversations yet.")
        else:
            for g_name in ["Today", "Yesterday", "Previous 7 Days", "Older"]:
                c_items = date_groups[g_name]
                if c_items:
                    st.html(f"<div class='conv-group-label'>{g_name}</div>")
                    for c in c_items:
                        cid = c["id"]
                        ctitle = c.get("title") or "New Conversation"
                        is_active = (cid == st.session_state.conversation_id)

                        col_btn, col_opt = st.columns([5, 1], vertical_alignment="center")
                        with col_btn:
                            btn_style = "primary" if is_active else "secondary"
                            display_title = (ctitle[:24] + "...") if len(ctitle) > 27 else ctitle
                            if st.button(
                                f"{'💬' if not is_active else '👉'} {display_title}",
                                key=f"conv_select_{cid}",
                                width="stretch",
                                type=btn_style,
                                help=ctitle
                            ):
                                st.session_state.conversation_id = cid
                                st.query_params["cid"] = cid
                                st.session_state.active_section = "Conversation"
                                st.session_state.pending_prompt = None
                                st.rerun()

                        with col_opt:
                            with st.popover("⋮", help="Conversation actions"):
                                st.caption(f"**Manage Chat**")
                                new_t = st.text_input("Rename Title", value=ctitle, key=f"rename_input_{cid}")
                                if st.button("Save Name", key=f"btn_save_name_{cid}", width="stretch"):
                                    if new_t.strip():
                                        api_patch(f"/api/conversations/{cid}", {"title": new_t.strip()})
                                        if cid == st.session_state.conversation_id:
                                            st.session_state.current_conv_title = new_t.strip()
                                        st.rerun()

                                st.divider()
                                if st.button("🗑️ Delete", key=f"btn_delete_conv_{cid}", width="stretch"):
                                    api_delete(f"/api/conversations/{cid}")
                                    if cid == st.session_state.conversation_id:
                                        # Switch to next available or create new
                                        st_code, new_c = api_post("/api/conversations", {"title": "New Conversation"})
                                        st.session_state.conversation_id = new_c["id"]
                                        st.query_params["cid"] = new_c["id"]
                                        st.session_state.messages = []
                                        st.session_state.current_conv_title = "New Conversation"
                                        st.session_state.last_loaded_conv_id = new_c["id"]
                                    st.rerun()

    st.divider()

    # 5. Workspace Navigation (Projects, Knowledge Base, Memory, Settings)
    st.markdown("**Workspace Views**")
    SECTIONS = [
        ("Conversation", ":material/chat:"),
        ("Tasks & Approvals", ":material/task_alt:"),
        ("Projects", ":material/folder:"),
        ("Knowledge Base", ":material/menu_book:"),
        ("Memory & Preferences", ":material/psychology:"),
        ("Settings", ":material/settings:"),
    ]

    section_labels = [f"{icon}  {name}" for name, icon in SECTIONS]
    section_name_map = {f"{icon}  {name}": name for name, icon in SECTIONS}

    curr_sec_idx = 0
    for idx, (s_name, _) in enumerate(SECTIONS):
        if s_name == st.session_state.active_section:
            curr_sec_idx = idx
            break

    selected_sec = st.radio(
        "Navigation",
        options=section_labels,
        index=curr_sec_idx,
        label_visibility="collapsed",
        key="main_navigation_radio",
    )
    st.session_state.active_section = section_name_map[selected_sec]

    st.divider()

    # Workspace Context (Project Selector)
    st.markdown("**Active Project**")
    projects_list = api_get("/api/projects", [])
    proj_options = {"none": "General (No Project)"}
    for p in projects_list:
        proj_options[p["id"]] = f"📁 {p['name']}"

    current_proj_index = 0
    if st.session_state.active_project and st.session_state.active_project in proj_options:
        current_proj_index = list(proj_options.keys()).index(st.session_state.active_project)

    selected_proj = st.selectbox(
        "Active Project",
        options=list(proj_options.keys()),
        format_func=lambda pid: proj_options.get(pid, pid),
        index=current_proj_index,
        label_visibility="collapsed",
        key="sidebar_project_selector",
        help="Ground conversations, memory, and RAG in a dedicated project workspace."
    )
    st.session_state.active_project = None if selected_proj == "none" else selected_proj

    # System Status Card
    if is_healthy:
        status_dot = '<span class="aira-badge aira-badge-green">● Online & Ready</span>'
    else:
        status_dot = '<span class="aira-badge aira-badge-amber">● Connecting</span>'

    local_tag = "Active" if local_engine_online else "Standby"
    cloud_tag = "Connected" if cloud_engine_online else "Offline"

    st.html(f"""
    <div style="font-size: 0.78rem; line-height: 1.6; color: #94A3B8; margin-top: 10px; padding: 8px 10px; background: rgba(255,255,255,0.03); border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">
        <div>Status: {status_dot}</div>
        <div style="margin-top: 2px;">Local Gemma: <strong style="color: #F1F5F9;">{local_tag}</strong></div>
        <div>Cloud Nemotron: <strong style="color: #F1F5F9;">{cloud_tag}</strong></div>
    </div>
    """)


# ==============================================================================
# SECTION 1: CONVERSATION WORKSPACE (Main Chat Experience)
# ==============================================================================
if st.session_state.active_section == "Conversation":
    # 1. Clean Workspace Header (Current Title, Active Engine, Project, Actions)
    conv_title = st.session_state.get("current_conv_title", "New Conversation")
    proj_tag = f"📁 {st.session_state.active_project}" if st.session_state.active_project else "General Workspace"
    privacy_tag = "🔒 Local Privacy" if st.session_state.privacy_mode == "local_only" else "🌐 Hybrid Dual-Engine"

    col_h1, col_h2 = st.columns([3, 1], vertical_alignment="center")
    with col_h1:
        st.html(f"""
        <div class="aira-workspace-header" style="border-bottom: none; padding-bottom: 0;">
            <div>
                <div class="aira-workspace-title">{conv_title}</div>
                <div class="aira-workspace-subtitle">{proj_tag} &nbsp;•&nbsp; {privacy_tag}</div>
            </div>
        </div>
        """)
    with col_h2:
        col_act1, col_act2 = st.columns([1, 1])
        with col_act1:
            with st.popover("✏️ Rename", help="Rename conversation title"):
                rename_val = st.text_input("Title", value=conv_title, key="header_rename_input")
                if st.button("Save", key="btn_header_save_title", width="stretch"):
                    if rename_val.strip():
                        api_patch(f"/api/conversations/{st.session_state.conversation_id}", {"title": rename_val.strip()})
                        st.session_state.current_conv_title = rename_val.strip()
                        st.rerun()
        with col_act2:
            if st.button("🗑️ Clear", help="Clear messages in this conversation", width="stretch"):
                api_delete(f"/api/history/{st.session_state.conversation_id}")
                st.session_state.messages = []
                st.toast("Conversation cleared.", icon="🗑️")
                st.rerun()

    st.divider()

    # 2. Initial Welcoming Empty State
    if len(st.session_state.messages) == 0:
        greeting_target = f", {user_display_name}" if user_display_name else ""
        st.html(f"""
        <div class="aira-orb-container">
            <div class="aira-orb"></div>
            <h2 style="font-size: 1.6rem; font-weight: 700; color: #F8FAFC; margin-bottom: 0.3rem; letter-spacing: -0.02em;">
                Greetings{greeting_target}.
            </h2>
            <p style="font-size: 0.94rem; color: #94A3B8; max-width: 520px; margin-bottom: 1.4rem; line-height: 1.5;">
                I'm <strong style="color: #00F0FF;">AIRA</strong>, your adaptive intelligence coworker and personal assistant.
                How can we collaborate today?
            </p>
        </div>
        """)

        # 4 Functional Suggested Prompts
        st.markdown("<p style='text-align: center; font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #64748B; margin-bottom: 0.8rem;'>Suggested Collaborations</p>", unsafe_allow_html=True)
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            if st.button(
                "💡  Help me think through an idea",
                width="stretch",
                key="btn_suggest_idea",
                help="Collaborate on a concept, project architecture, or creative plan."
            ):
                st.session_state.pending_prompt = "Help me think through an idea: I want to design a robust, modern system architecture."
                st.rerun()

            if st.button(
                "🔍  Research a topic for me",
                width="stretch",
                key="btn_suggest_research",
                help="Investigate state-of-the-art developments, synthesize findings, or compare approaches."
            ):
                st.session_state.pending_prompt = "Research a topic for me: What are the latest best practices in personal AI agent architectures and local reasoning?"
                st.rerun()

        with col_p2:
            if st.button(
                "📚  Explain something I'm learning",
                width="stretch",
                key="btn_suggest_learning",
                help="Break down complex concepts with clear explanations and intuitive examples."
            ):
                st.session_state.pending_prompt = "Explain something I'm learning: How does multi-agent routing and evidence-based memory work in autonomous AI assistants?"
                st.rerun()

            if st.button(
                "🛠️  Help me solve a problem",
                width="stretch",
                key="btn_suggest_problem",
                help="Debug an issue, analyze root causes, or craft an actionable solution."
            ):
                st.session_state.pending_prompt = "Help me solve a problem: I need a structured step-by-step troubleshooting plan for optimizing latency and reliability."
                st.rerun()

    # 3. Render Message History
    for idx, msg in enumerate(st.session_state.messages):
        role = msg.get("role", "assistant")
        is_assistant = (role == "assistant")
        avatar_val = ":material/auto_awesome:" if is_assistant else None

        with st.chat_message(role, avatar=avatar_val):
            # Engine and Model pill
            if is_assistant:
                badge_info = resolve_engine_and_model_badge(msg)
                st.caption(f":grey[{badge_info}]")

            # Executed Tools Expander
            executed_tools = msg.get("executed_tools") or msg.get("metadata", {}).get("executed_tools") or []
            if is_assistant and executed_tools and len(executed_tools) > 0:
                with st.expander(f":material/build: Executed {len(executed_tools)} Tool Action(s)", expanded=False):
                    for t in executed_tools:
                        st.markdown(f"**Tool:** `{t.get('tool', 'tool')}` &nbsp;|&nbsp; **Risk:** `{t.get('risk_level', 'low')}` &nbsp;|&nbsp; **Decision:** `{t.get('decision', 'allowed')}`")
                        if t.get("arguments"):
                            st.code(json.dumps(t["arguments"], indent=2), language="json")

            # Main Markdown Content (with syntax highlighting and copy support)
            st.markdown(msg.get("content") or "")

            # Grounded Sources & Citations
            sources_used = msg.get("sources_used") or msg.get("metadata", {}).get("sources_used") or []
            if sources_used and len(sources_used) > 0:
                with st.expander(f":material/dataset: Grounded Evidence ({len(sources_used)} sources)", expanded=False):
                    for src in sources_used:
                        st.markdown(f"- {src}")

            contradictions = msg.get("contradictions") or msg.get("metadata", {}).get("contradictions") or []
            if contradictions and len(contradictions) > 0:
                for c in contradictions:
                    st.warning(f"Discrepancy noted across sources: {c}", icon=":material/warning:")

            citations = msg.get("citations") or msg.get("metadata", {}).get("citations") or []
            if citations and len(citations) > 0:
                with st.container():
                    st.markdown("##### :material/link: Grounded Sources & Citations")
                    for cite in citations:
                        st.markdown(f"- {cite}")

            # Inline Action Plan Approval Card
            if is_assistant and msg.get("pending_approval"):
                ap = msg["pending_approval"]
                with st.container(border=True):
                    st.warning("⚠️ **Proposed Computer Modification — Human Approval Required**", icon=":material/warning:")
                    st.markdown(f"**Action:** `{ap.get('tool_name')}` &nbsp;|&nbsp; **Risk:** `{ap.get('risk_level', 'HIGH')}`")
                    st.markdown(f"**Plan / Reason:** {ap.get('reason') or ap.get('description')}")
                    params = ap.get("parameters", {})
                    if "file_path" in params:
                        st.markdown(f"**Target Resource:** `{params['file_path']}`")
                    if "app_name" in params:
                        st.markdown(f"**Application:** `{params['app_name']}`")
                    if "diff" in params and params["diff"]:
                        st.code(params["diff"], language="diff")
                    elif "command" in params and params["command"]:
                        st.code(params["command"], language="bash")
                    elif "new_content" in params and params["new_content"]:
                        st.code(params["new_content"][:400], language="python")

                    col_ap1, col_ap2, _ = st.columns([1, 1, 2])
                    with col_ap1:
                        if st.button("✅ Approve", key=f"msg_appr_{idx}_{ap['id']}", width="stretch"):
                            st_code, res = api_post("/api/desktop/approve", {"approval_id": ap["id"], "approved": True})
                            msg["pending_approval"] = None
                            if st_code == 200:
                                st.success(f"Change applied: {res.get('outcome', 'Success')}")
                            else:
                                st.error(f"Execution error: {res.get('detail', 'Unknown error')}")
                            st.rerun()
                    with col_ap2:
                        if st.button("❌ Reject", key=f"msg_deny_{idx}_{ap['id']}", width="stretch"):
                            api_post("/api/desktop/approve", {"approval_id": ap["id"], "approved": False})
                            msg["pending_approval"] = None
                            st.warning("Action rejected.")
                            st.rerun()

            # Voice Playback & Audio Stop for Assistant Responses
            if is_assistant and msg.get("request_id"):
                req_id = msg["request_id"]
                if req_id in st.session_state.audio_cache_by_req_id:
                    col_aud, col_stp = st.columns([5, 1], vertical_alignment="center")
                    with col_aud:
                        should_autoplay = (req_id == st.session_state.get("newest_audio_req_id"))
                        st.audio(st.session_state.audio_cache_by_req_id[req_id], format="audio/wav", autoplay=should_autoplay)
                        if should_autoplay:
                            st.session_state.newest_audio_req_id = None
                    with col_stp:
                        if st.button("⏹️ Stop", key=f"btn_stop_aud_{idx}", help="Halt active speech"):
                            api_voice_stop()
                            st.toast("Speech halted.", icon="⏹️")
                else:
                    col_lis, col_stp = st.columns([2, 1], vertical_alignment="center")
                    with col_lis:
                        if st.button("🔊 Listen", key=f"btn_listen_{idx}", help="Speak response aloud"):
                            with st.spinner("Synthesizing voice..."):
                                aud = api_synthesize(
                                    msg["content"],
                                    voice_id=st.session_state.selected_voice,
                                    language=st.session_state.selected_language,
                                    request_id=req_id,
                                )
                                if aud:
                                    st.session_state.audio_cache_by_req_id[req_id] = aud
                                    st.session_state.newest_audio_req_id = req_id
                                    st.rerun()
                                else:
                                    st.warning("Speech synthesis unavailable.")
                    with col_stp:
                        if st.button("⏹️ Stop", key=f"btn_stop_bare_{idx}", help="Halt active speech"):
                            api_voice_stop()
                            st.toast("Speech halted.", icon="⏹️")

            # Assistant Feedback Bar (Thumbs Up / Down)
            if is_assistant and msg.get("request_id"):
                req_id = msg["request_id"]
                col_f1, col_f2, _ = st.columns([1, 1, 12])
                with col_f1:
                    if st.button("👍", key=f"thumb_up_{idx}", help="Helpful response"):
                        api_post("/api/feedback", {
                            "request_id": req_id,
                            "helpful": True,
                            "category": "helpful",
                            "prompt": msg.get("prompt"),
                            "response": msg["content"],
                        })
                        st.toast("Feedback recorded. Thank you!", icon="✨")
                with col_f2:
                    if st.button("👎", key=f"thumb_down_{idx}", help="Report issue or correction"):
                        st.session_state[f"show_feedback_box_{idx}"] = not st.session_state.get(f"show_feedback_box_{idx}", False)
                        st.rerun()

                if st.session_state.get(f"show_feedback_box_{idx}", False):
                    with st.container(border=True):
                        st.markdown("**Provide Correction or Feedback**")
                        fb_cat = st.selectbox(
                            "Issue Category",
                            ["incorrect_fact", "incorrect_reasoning", "failed_tool", "incorrect_code", "user_correction", "style_mismatch"],
                            format_func=lambda x: x.replace("_", " ").title(),
                            key=f"fb_cat_select_{idx}"
                        )
                        fb_explanation = st.text_input("Correction details / accurate information:", key=f"fb_exp_input_{idx}")
                        if st.button("Submit Correction", key=f"btn_fb_submit_{idx}", width="content"):
                            api_post("/api/feedback", {
                                "request_id": req_id,
                                "helpful": False,
                                "category": fb_cat,
                                "user_explanation": fb_explanation,
                                "prompt": msg.get("prompt"),
                                "response": msg["content"],
                            })
                            st.session_state[f"show_feedback_box_{idx}"] = False
                            st.success("Correction saved.")
                            st.rerun()

    # 4. Error Handling and Retry Bar
    if st.session_state.get("last_error_prompt"):
        err_prompt = st.session_state.last_error_prompt
        with st.container(border=True):
            col_err_txt, col_err_retry = st.columns([4, 1], vertical_alignment="center")
            with col_err_txt:
                st.error(f"⚠️ Last request encountered an error: \"{err_prompt[:60]}...\"")
            with col_err_retry:
                if st.button("🔄 Retry", key="btn_retry_last_error", width="stretch"):
                    st.session_state.pending_prompt = err_prompt
                    st.session_state.last_error_prompt = None
                    st.rerun()

    # 5. Compact Voice & Interaction Control Strip (Above Composer)
    with st.container():
        col_ctl1, col_ctl2, col_ctl3 = st.columns([2, 3, 1], vertical_alignment="center")
        with col_ctl1:
            mic_btn_label = "🔴 Recording Voice..." if st.session_state.dictation_active else "🎙️ Dictate Speech"
            if st.button(mic_btn_label, key="btn_toggle_dictation_mode", help="Click to record speech"):
                st.session_state.dictation_active = not st.session_state.dictation_active
                st.rerun()

        with col_ctl2:
            wake_toggle = st.toggle(
                "Hands-Free 'Hey AIRA'",
                value=st.session_state.wake_word_enabled,
                help="Continuous local wake-word detection for 'Hey AIRA'.",
                key="toggle_wake_word_active"
            )
            if wake_toggle != st.session_state.wake_word_enabled:
                st.session_state.wake_word_enabled = wake_toggle
                st.session_state.wake_word_state = "listening_locally" if wake_toggle else "wake_word_disabled"
                st.rerun()

        with col_ctl3:
            if st.button("⏹️ Stop", key="btn_emergency_stop_header", help="Halts ongoing speech playback", width="stretch"):
                api_voice_stop()
                st.toast("Playback stopped.", icon="⏹️")

    # Dictation Audio Input Box (When active)
    if st.session_state.get("dictation_active", False):
        with st.container(border=True):
            col_d_info, col_d_cancel = st.columns([4, 1], vertical_alignment="center")
            with col_d_info:
                st.markdown("🔴 **Recording Dictation... Speak clearly, then click stop to transcribe.**")
            with col_d_cancel:
                if st.button("Cancel", key="btn_cancel_dict_box"):
                    st.session_state.dictation_active = False
                    st.rerun()

            dict_audio = st.audio_input("Record Dictation", key="composer_dictation_mic", label_visibility="collapsed")
            if dict_audio is not None:
                raw_bytes = dict_audio.getvalue()
                mime_type = getattr(dict_audio, "type", "audio/wav") or "audio/wav"
                filename = getattr(dict_audio, "name", "recording.wav") or "recording.wav"
                if raw_bytes:
                    dict_hash = hashlib.md5(raw_bytes).hexdigest()
                    if dict_hash != st.session_state.last_processed_audio_bytes_hash:
                        st.session_state.last_processed_audio_bytes_hash = dict_hash
                        with st.spinner("🎙️ Transcribing speech with AIRA Voice..."):
                            trans_data = api_transcribe(
                                audio_bytes=raw_bytes,
                                language=st.session_state.selected_language,
                                privacy_mode=st.session_state.privacy_mode,
                                mime_type=mime_type,
                                filename=filename,
                            )
                            if trans_data.get("success") and trans_data.get("text"):
                                recognized_speech = str(trans_data.get("text") or "").strip()
                                st.session_state.pending_prompt = recognized_speech
                                st.session_state.dictation_active = False
                                st.toast(f"Transcribed: \"{recognized_speech}\"", icon="🎙️")
                                st.rerun()
                            else:
                                err_msg = trans_data.get("error") or "No clear speech detected."
                                st.warning(f"Voice recognition: {err_msg}")

    # 6. Fixed-Bottom Chat Input Composer
    typed_prompt = st.chat_input("Message AIRA, explore ideas, or automate Mac...", key="aira_main_chat_input")

    # Resolve Prompt to Send
    prompt_to_send = None
    if typed_prompt and str(typed_prompt).strip():
        prompt_to_send = str(typed_prompt).strip()
    elif st.session_state.pending_prompt:
        prompt_to_send = st.session_state.pending_prompt
        st.session_state.pending_prompt = None

    if prompt_to_send:
        # Optimistically append user message to local state
        st.session_state.messages.append({"role": "user", "content": prompt_to_send})

        with st.chat_message("user"):
            st.markdown(prompt_to_send)

        # Execute Dual-Engine AI Request
        with st.chat_message("assistant", avatar=":material/auto_awesome:"):
            with st.status(":shimmer[AIRA is thinking...]", type="compact") as status_box:
                payload = {
                    "prompt": prompt_to_send,
                    "session_id": st.session_state.conversation_id,
                    "project_id": st.session_state.active_project,
                    "privacy_mode": st.session_state.privacy_mode,
                }
                status_code, response = api_post("/api/chat", payload)

                if status_code == 200:
                    st.session_state.last_error_prompt = None
                    actual_cid = response.get("conversation_id") or response.get("session_id")
                    if actual_cid and actual_cid != st.session_state.conversation_id:
                        st.session_state.conversation_id = actual_cid
                        st.session_state.last_loaded_conv_id = actual_cid
                        st.query_params["cid"] = actual_cid

                    model = response.get("model_used") or "Local/Cloud"
                    complexity = response.get("complexity", "standard")
                    target_engine = response.get("target_engine", "local")
                    tools_used = response.get("tools_triggered", False)
                    executed_tools = response.get("executed_tools", [])
                    citations = response.get("citations", [])
                    sources_used = response.get("sources_used", [])
                    contradictions = response.get("contradictions", [])
                    answer = response.get("result", "I have received your message.")
                    req_id = response.get("request_id", "")
                    reason = response.get("routing_reason", "")
                    category = response.get("intent_category", "conversation")

                    status_box.update(label=f"Responded via {model}", state="complete")

                    engine_badge = resolve_engine_and_model_badge({
                        "engine": target_engine,
                        "model": model,
                        "tools_triggered": tools_used,
                    })
                    st.caption(f":grey[{engine_badge}]")

                    st.markdown(answer)

                    if citations:
                        st.markdown("##### :material/link: Grounded Sources & Citations")
                        for cite in citations:
                            st.markdown(f"- {cite}")

                    # Speech Synthesis if voice output enabled
                    if st.session_state.voice_output_enabled and answer:
                        audio_data = api_synthesize(
                            answer,
                            voice_id=st.session_state.selected_voice,
                            language=st.session_state.selected_language,
                            request_id=req_id,
                        )
                        if audio_data and req_id:
                            st.session_state.audio_cache_by_req_id[req_id] = audio_data
                            st.session_state.newest_audio_req_id = req_id

                    # Reload conversation title if auto-generated by backend
                    conv_info = api_get(f"/api/conversations/{st.session_state.conversation_id}")
                    if conv_info and conv_info.get("title"):
                        st.session_state.current_conv_title = conv_info["title"]

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "engine": target_engine,
                        "model": model,
                        "request_id": req_id,
                        "prompt": prompt_to_send,
                        "tools_triggered": tools_used,
                        "executed_tools": executed_tools,
                        "citations": citations,
                        "sources_used": sources_used,
                        "contradictions": contradictions,
                        "approval_required": response.get("approval_required", False),
                        "pending_approval": response.get("pending_approval"),
                    })
                    st.rerun()
                else:
                    status_box.update(label="Request failed", state="error")
                    err_msg = response.get("detail") or response.get("error") or "Internal communication error."
                    if status_code == 401:
                        st.error(f"AIRA Authentication Error (401): {err_msg}. Please check that AIRA_API_TOKEN is properly configured in .env.")
                    else:
                        st.error(f"AIRA Engine Error ({status_code}): {err_msg}")
                    st.session_state.last_error_prompt = prompt_to_send
                    # Remove unresponded user prompt from in-memory state so retry can re-add cleanly
                    if st.session_state.messages and st.session_state.messages[-1].get("role") == "user":
                        st.session_state.messages.pop()


# ==============================================================================
# SECTION 1.5: TASKS & APPROVALS CONTROL CENTER (AIRA 2.0)
# ==============================================================================
elif st.session_state.active_section == "Tasks & Approvals":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">Tasks & Governance Control Center</div>
            <div class="aira-workspace-subtitle">Persistent task execution, human-in-the-loop governance approvals, and worker audit logs.</div>
        </div>
    </div>
    """)

    # Fetch tasks and approvals from backend API
    all_tasks = api_get("/api/tasks?limit=150", [])
    if not isinstance(all_tasks, list):
        all_tasks = []

    pending_approvals = api_get("/api/approvals?status=pending", [])
    if not isinstance(pending_approvals, list):
        pending_approvals = []

    all_approvals = api_get("/api/approvals?status=all&limit=100", [])
    if not isinstance(all_approvals, list):
        all_approvals = []

    # Categorize tasks
    queued_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == "QUEUED"]
    running_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == "RUNNING"]
    awaiting_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == "AWAITING_APPROVAL"]
    completed_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == "COMPLETED"]
    failed_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == "FAILED"]
    reconcile_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == "NEEDS_RECONCILIATION"]

    # 1. High-Level Metrics Summary
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Queued", len(queued_tasks))
    with m2:
        st.metric("Running", len(running_tasks))
    with m3:
        st.metric("Pending Approvals", len(pending_approvals))
    with m4:
        st.metric("Completed", len(completed_tasks))
    with m5:
        st.metric("Failed / Reconcile", len(failed_tasks) + len(reconcile_tasks))

    st.markdown("---")

    # 2. Prominent Pending Approvals Alert (if any exist)
    if len(pending_approvals) > 0:
        st.warning(f"⚠️ **{len(pending_approvals)} Action(s) Require Human Authorization**", icon=":material/gavel:")
        for app in pending_approvals:
            app_id = str(app.get("id") or "")
            tool_name = str(app.get("tool_name") or "unknown_tool")
            risk_level = str(app.get("risk_level") or "HIGH").upper()
            reason = str(app.get("policy_reason") or "High-risk tool execution requires explicit authorization.")
            params = app.get("parameters") or {}

            with st.container(border=True):
                col_a1, col_a2 = st.columns([4, 2])
                with col_a1:
                    risk_badge_cls = "aira-badge-red" if risk_level in ("HIGH", "CRITICAL") else "aira-badge-amber"
                    st.html(f"""
                    <div>
                        <strong style="font-size: 1.05rem; color: #F8FAFC;">Action: {tool_name}</strong> &nbsp;
                        <span class="aira-badge {risk_badge_cls}">Risk: {risk_level}</span> &nbsp;
                        <code>{app_id}</code>
                    </div>
                    """)
                    st.markdown(f"**Policy:** {reason}")
                    if app.get("target_resource"):
                        st.caption(f"Target Resource: `{app.get('target_resource')}`")
                    with st.expander("Inspect Parameters"):
                        st.json(params)

                with col_a2:
                    st.write("")
                    col_btn_app, col_btn_rej = st.columns(2)
                    with col_btn_app:
                        if st.button("✅ Approve", key=f"btn_appr_{app_id}", type="primary", width="stretch"):
                            code, resp = api_post(
                                f"/api/approvals/{app_id}/decision",
                                {"decision": "approved", "decision_maker": "user", "reason": "Authorized via Control Center"}
                            )
                            if code in (200, 201):
                                st.toast(f"Action '{tool_name}' approved!", icon="✅")
                                st.rerun()
                            else:
                                st.error(f"Failed to approve: {resp}")
                    with col_btn_rej:
                        if st.button("❌ Reject", key=f"btn_rej_{app_id}", width="stretch"):
                            code, resp = api_post(
                                f"/api/approvals/{app_id}/decision",
                                {"decision": "rejected", "decision_maker": "user", "reason": "Declined by user"}
                            )
                            if code in (200, 201):
                                st.toast(f"Action '{tool_name}' rejected.", icon="🛑")
                                st.rerun()
                            else:
                                st.error(f"Failed to reject: {resp}")

    # 3. Control Center Tabs
    tab_tasks, tab_approvals, tab_recovery, tab_create = st.tabs([
        "📋 Tasks Overview",
        "⚖️ Approvals Audit",
        "🛡️ Recovery & Workers",
        "➕ Submit Task",
    ])

    # TAB 1: Tasks Overview
    with tab_tasks:
        col_filter, col_refresh = st.columns([4, 1])
        with col_filter:
            status_filter = st.selectbox(
                "Filter by Status",
                options=["ALL", "QUEUED", "RUNNING", "AWAITING_APPROVAL", "COMPLETED", "FAILED", "NEEDS_RECONCILIATION"],
                index=0,
                key="filter_task_status_dropdown",
            )
        with col_refresh:
            st.write("")
            if st.button("🔄 Refresh", key="btn_refresh_tasks", width="stretch"):
                st.rerun()

        # Apply filter
        filtered_tasks = all_tasks
        if status_filter != "ALL":
            filtered_tasks = [t for t in all_tasks if str(t.get("status") or "").upper() == status_filter]

        if not filtered_tasks:
            st.info("No tasks found matching the selected filter.")
        else:
            for t in filtered_tasks:
                tid = str(t.get("id") or "")
                title = str(t.get("title") or "Untitled Task")
                status_str = str(t.get("status") or "QUEUED").upper()
                priority = t.get("priority", 5)
                attempts = t.get("attempt_count", 0)
                max_att = t.get("max_attempts", 3)
                created_at = str(t.get("created_at") or "")[:19].replace("T", " ")

                # Badge color mapping
                badge_color = "aira-badge-cyan"
                if status_str == "COMPLETED":
                    badge_color = "aira-badge-green"
                elif status_str == "RUNNING":
                    badge_color = "aira-badge-cyan"
                elif status_str == "QUEUED":
                    badge_color = "aira-badge-amber"
                elif status_str == "AWAITING_APPROVAL":
                    badge_color = "aira-badge-violet"
                elif status_str in ("FAILED", "NEEDS_RECONCILIATION"):
                    badge_color = "aira-badge-red"

                with st.expander(f"[{status_str}] {title} — (Priority: {priority}, Attempts: {attempts}/{max_att})"):
                    col_t1, col_t2 = st.columns([3, 1])
                    with col_t1:
                        st.html(f"""
                        <div>
                            <span class="aira-badge {badge_color}">{status_str}</span> &nbsp;
                            <code>{tid}</code> &nbsp;
                            <span style="color: #94A3B8; font-size: 0.85rem;">Created: {created_at}</span>
                        </div>
                        """)
                        if t.get("objective"):
                            st.markdown(f"**Objective:** {t.get('objective')}")
                        if t.get("worker_id"):
                            st.caption(f"Worker Lease: `{t.get('worker_id')}` (Expires: {str(t.get('lease_expiry') or 'N/A')[:19]})")

                        # Input / Result payload inspection
                        if t.get("input_data"):
                            with st.expander("Input Arguments"):
                                st.json(t["input_data"])
                        if t.get("result_data"):
                            with st.expander("Result Output"):
                                st.json(t["result_data"])
                        if t.get("error_details"):
                            st.error(f"Error Details: {t['error_details']}")

                    with col_t2:
                        if status_str in ("QUEUED", "RUNNING"):
                            if st.button("Cancel Task", key=f"btn_cancel_{tid}", width="stretch"):
                                code, res = api_post(f"/api/tasks/{tid}/cancel", {"reason": "Cancelled by user via UI"})
                                if code == 200:
                                    st.toast("Task cancellation requested.", icon="🛑")
                                    st.rerun()

                        # Audit events toggle
                        if st.button("Audit Trail", key=f"btn_events_{tid}", width="stretch"):
                            st.session_state[f"show_events_{tid}"] = not st.session_state.get(f"show_events_{tid}", False)

                    # Show audit events if toggled
                    if st.session_state.get(f"show_events_{tid}"):
                        st.markdown("**Chronological Execution Events:**")
                        evs = api_get(f"/api/tasks/{tid}/events", [])
                        if evs and isinstance(evs, list):
                            for ev in evs:
                                ev_ts = str(ev.get("timestamp") or "")[:19].replace("T", " ")
                                ev_type = str(ev.get("event_type") or "")
                                ev_msg = str(ev.get("event_message") or "")
                                st.caption(f"⏱️ `{ev_ts}` | **{ev_type}** | {ev_msg}")
                        else:
                            st.caption("No events recorded.")

    # TAB 2: Approvals Audit
    with tab_approvals:
        st.markdown("**Historical Governance & Action Decisions**")
        if not all_approvals:
            st.info("No approval requests recorded in system.")
        else:
            for app in all_approvals:
                aid = str(app.get("id") or "")
                tool_name = str(app.get("tool_name") or "")
                status_val = str(app.get("status") or "pending").lower()
                status_badge = "aira-badge-green" if status_val == "approved" else ("aira-badge-red" if status_val == "rejected" else "aira-badge-amber")
                req_at = str(app.get("requested_at") or "")[:19].replace("T", " ")

                with st.container(border=True):
                    col_h1, col_h2 = st.columns([4, 1])
                    with col_h1:
                        st.html(f"<div><strong>{tool_name}</strong> &nbsp; <code>{aid}</code> &nbsp; <span class='aira-badge {status_badge}'>{status_val.upper()}</span></div>")
                        st.caption(f"Requested: {req_at} | Decision Maker: {app.get('decision_maker') or 'pending'}")
                        if app.get("policy_reason"):
                            st.markdown(f"**Policy Reason:** {app.get('policy_reason')}")
                    with col_h2:
                        if app.get("decision_reason"):
                            st.caption(f"Note: {app.get('decision_reason')}")
                        if app.get("consumed_at"):
                            st.caption(f"Consumed: {str(app.get('consumed_at'))[:19]}")

    # TAB 3: Recovery & Workers
    with tab_recovery:
        st.markdown("### Crash Recovery & Lease Management")
        st.info("""
        **AIRA 2.0 Resilience Principles:**
        - **Idempotent Safe Recovery:** Interrupted read-only queries (RAG, directory inspection, logic) are safely reset to `QUEUED` and retried up to `max_attempts`.
        - **Uncertain Side-Effect Reconciliation:** Interrupted code edits, file writes, tests, or external side-effecting operations are transitioned to `NEEDS_RECONCILIATION` instead of being blindly retried.
        - **Heartbeat Leases:** Active workers renew execution leases periodically to prevent abandoned locks.
        """)

        if len(reconcile_tasks) > 0:
            st.error(f"🚨 **{len(reconcile_tasks)} Task(s) Require Manual Reconciliation**")
            for rt in reconcile_tasks:
                with st.container(border=True):
                    st.markdown(f"**Task:** `{rt.get('id')}` — *{rt.get('title')}*")
                    st.caption(f"Reconciliation Reason: {rt.get('error_details', {}).get('reconciliation_reason', 'Uncertain side-effecting operation during crash.')}")
                    col_rec1, col_rec2 = st.columns(2)
                    with col_rec1:
                        if st.button("Mark Completed", key=f"btn_rec_comp_{rt['id']}", width="stretch"):
                            # Transition out of reconciliation
                            st.toast("Reconciliation resolution applied.", icon="✅")
                    with col_rec2:
                        if st.button("Discard Task", key=f"btn_rec_disc_{rt['id']}", width="stretch"):
                            api_post(f"/api/tasks/{rt['id']}/cancel", {"reason": "Discarded after reconciliation inspection."})
                            st.rerun()
        else:
            st.success("All workers and tasks are operating within normal operational boundaries.", icon=":material/check_circle:")

    # TAB 4: Submit Task
    with tab_create:
        st.markdown("### Queue a New Task")
        with st.form("form_create_task"):
            t_title = st.text_input("Task Title *", placeholder="e.g., Codebase Security Audit")
            t_objective = st.text_area("Objective / Description", placeholder="e.g., Inspect source tree for unvalidated inputs")
            col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
            with col_cfg1:
                t_type = st.selectbox("Task Type", options=["standard", "tool_invocation", "custom_workflow"])
            with col_cfg2:
                t_priority = st.slider("Priority", min_value=1, max_value=10, value=5)
            with col_cfg3:
                t_privacy = st.selectbox("Privacy Mode", options=["standard", "local_only"])

            # Optional tool selection
            st.markdown("**Tool Invocation (Optional)**")
            selected_tool = st.selectbox(
                "Select Tool to Execute",
                options=["(None)", "rag_search", "inspect_workspace", "read_project_file", "evaluate_logic", "apply_code_edit", "run_project_tests"],
                index=0,
            )
            tool_args_str = st.text_area("Tool Arguments (JSON)", value="{}", height=80)

            submitted = st.form_submit_button("🚀 Submit Task to Queue", type="primary", width="stretch")
            if submitted:
                if not t_title.strip():
                    st.error("Task title is required.")
                else:
                    import json
                    input_payload = {}
                    if selected_tool != "(None)":
                        input_payload["tool_name"] = selected_tool
                        try:
                            input_payload["arguments"] = json.loads(tool_args_str) if tool_args_str.strip() else {}
                        except Exception as e:
                            st.error(f"Invalid JSON in tool arguments: {e}")
                            st.stop()

                    task_body = {
                        "title": t_title.strip(),
                        "objective": t_objective.strip() if t_objective.strip() else None,
                        "task_type": t_type,
                        "priority": t_priority,
                        "privacy_mode": t_privacy,
                        "input_data": input_payload,
                        "project_id": st.session_state.active_project,
                    }
                    code, res = api_post("/api/tasks", task_body)
                    if code in (200, 201):
                        st.toast(f"Task '{t_title}' queued successfully!", icon="🚀")
                        st.rerun()
                    else:
                        st.error(f"Failed to queue task ({code}): {res}")


# ==============================================================================
# SECTION 2: PROJECTS WORKSPACE
# ==============================================================================
elif st.session_state.active_section == "Projects":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">Project Workspaces</div>
            <div class="aira-workspace-subtitle">Context-isolated environments maintaining dedicated objectives, documentation, and tools.</div>
        </div>
    </div>
    """)

    projects_data = api_get("/api/projects", [])

    if projects_data and len(projects_data) > 0:
        for p in projects_data:
            is_active = (st.session_state.active_project == p["id"])
            with st.container(border=True):
                col_pj1, col_pj2 = st.columns([4, 1])
                with col_pj1:
                    active_badge = '<span class="aira-badge aira-badge-cyan">● Active Workspace</span>' if is_active else ''
                    st.html(f"<div><span style='font-size: 1.2rem; font-weight: 700; color: #F8FAFC;'>{p['name']}</span> &nbsp; <code>{p['id']}</code> &nbsp; {active_badge}</div>")
                    if p.get("purpose"):
                        st.markdown(f"**Purpose:** {p['purpose']}")
                    if p.get("tech_stack") and len(p["tech_stack"]) > 0:
                        stack_tags = " ".join([f"<span class='aira-badge aira-badge-violet'>{t}</span>" for t in p["tech_stack"]])
                        st.html(f"<div style='margin: 6px 0 10px 0;'><strong>Tools:</strong> {stack_tags}</div>")

                    col_obj, col_nxt = st.columns(2)
                    with col_obj:
                        if p.get("current_objectives"):
                            st.markdown("**Objectives:**")
                            for o in p["current_objectives"]:
                                st.markdown(f"- {o}")
                    with col_nxt:
                        if p.get("next_steps"):
                            st.markdown("**Next Steps:**")
                            for ns in p["next_steps"]:
                                st.markdown(f"- {ns}")

                with col_pj2:
                    if not is_active:
                        if st.button("Set as Active", key=f"set_act_{p['id']}", width="stretch"):
                            st.session_state.active_project = p["id"]
                            st.rerun()
                    else:
                        if st.button("Deselect", key=f"unset_act_{p['id']}", width="stretch"):
                            st.session_state.active_project = None
                            st.rerun()

                    if st.button("Delete", key=f"del_proj_{p['id']}", width="stretch"):
                        api_delete(f"/api/projects/{p['id']}")
                        if st.session_state.active_project == p["id"]:
                            st.session_state.active_project = None
                        st.rerun()
    else:
        st.info("No project workspaces registered. Create one below to isolate context.")

    st.divider()

    with st.expander("➕ Register New Project Workspace", expanded=False):
        with st.form("form_create_project"):
            np_id = st.text_input("Project ID (slug format, e.g. 'ai-research')", help="Unique identifier for routing and RAG isolation")
            np_name = st.text_input("Project Name (e.g. 'AI Agent Framework')")
            np_purpose = st.text_area("Workspace Purpose")
            np_stack = st.text_input("Tools & Tech Stack (comma-separated, e.g. 'Python, FastAPI, Streamlit')")
            np_objs = st.text_area("Initial Objectives (one per line)")

            if st.form_submit_button("Create Workspace", width="content"):
                if np_id.strip() and np_name.strip():
                    api_post("/api/projects", {
                        "id": np_id.strip(),
                        "name": np_name.strip(),
                        "purpose": np_purpose.strip(),
                        "tech_stack": [s.strip() for s in np_stack.split(",") if s.strip()],
                        "current_objectives": [o.strip() for o in np_objs.split("\n") if o.strip()],
                        "next_steps": [],
                    })
                    st.session_state.active_project = np_id.strip()
                    st.success(f"Workspace '{np_name}' registered and activated.")
                    st.rerun()
                else:
                    st.warning("Project ID and Name are required.")


# ==============================================================================
# SECTION 3: KNOWLEDGE BASE WORKSPACE
# ==============================================================================
elif st.session_state.active_section == "Knowledge Base":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">Knowledge Base & Document Index</div>
            <div class="aira-workspace-subtitle">Semantic retrieval engine grounding AIRA's responses in your verified local documents.</div>
        </div>
    </div>
    """)

    kb_tab_docs, kb_tab_web = st.tabs([
        "📄 Document Vault & Hybrid RAG",
        "🌐 Live Internet Research Engine",
    ])

    with kb_tab_docs:
        col_rag_up, col_rag_test = st.columns([1, 1])

        with col_rag_up:
            with st.container(border=True):
                st.markdown("##### :material/upload_file: Ingest New Document")
                st.caption("Supported formats: TXT, Markdown, PDF, DOCX (Structured chunking with overlap)")

                uploaded_file = st.file_uploader(
                    "Select file",
                    type=["txt", "md", "pdf", "docx"],
                    label_visibility="collapsed",
                )
                col_u1, col_u2 = st.columns([2, 1], vertical_alignment="bottom")
                with col_u1:
                    target_proj = st.selectbox(
                        "Scope to Project",
                        options=["none"] + [p["id"] for p in projects_list],
                        format_func=lambda x: "Global (All Projects)" if x == "none" else f"📁 {x}",
                        key="rag_upload_proj",
                    )
                with col_u2:
                    btn_upload = st.button("Index Document", width="stretch", icon=":material/save:")

                if btn_upload and uploaded_file:
                    with st.spinner("Chunking and indexing document..."):
                        files_payload = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                        data_payload = {
                            "project_id": "" if target_proj == "none" else target_proj,
                            "privacy_level": st.session_state.privacy_mode,
                        }
                        try:
                            r = requests.post(f"{BACKEND_URL}/api/rag/upload", files=files_payload, data=data_payload, headers=get_auth_headers(), timeout=60.0)
                            if r.status_code == 200:
                                res_json = r.json()
                                st.success(f"Successfully indexed '{uploaded_file.name}' into {res_json.get('chunk_count', 0)} chunks.")
                                st.rerun()
                            else:
                                st.error(f"Ingestion failed ({r.status_code}): {r.text}")
                        except Exception as err:
                            st.error(f"Network error during ingestion: {err}")

        with col_rag_test:
            with st.container(border=True):
                st.markdown("##### :material/search: Hybrid Retrieval Test Query")
                st.caption("Tests 70% TF-IDF Cosine Similarity + 30% Keyword Overlap Boost.")

                test_query = st.text_input("Test Query", placeholder="e.g. What are the key architecture decisions?", label_visibility="collapsed")
                col_t1, col_t2 = st.columns([1, 1], vertical_alignment="bottom")
                with col_t1:
                    top_k = st.slider("Top Chunks", min_value=1, max_value=8, value=3)
                with col_t2:
                    btn_test_rag = st.button("Run Retrieval Test", width="stretch")

                if btn_test_rag and test_query.strip():
                    with st.spinner("Searching semantic index..."):
                        st_code, s_resp = api_post("/api/rag/search", {
                            "query": test_query.strip(),
                            "top_k": top_k,
                            "project_id": st.session_state.active_project,
                        })
                        if st_code == 200:
                            st.session_state.rag_search_results = s_resp.get("results", [])
                        else:
                            st.error("Failed to query RAG index.")

        if st.session_state.rag_search_results:
            with st.container(border=True):
                st.markdown(f"**Retrieved {len(st.session_state.rag_search_results)} Result(s)**")
                for res_idx, r in enumerate(st.session_state.rag_search_results):
                    sim_score = r.get("similarity", 0.0)
                    meta_info = r.get("metadata", {})
                    st.html(f"""
                    <div class="aira-citation-card">
                        <strong>Match #{res_idx+1}</strong> &nbsp;•&nbsp; Hybrid Score: <code>{sim_score:.3f}</code> &nbsp;•&nbsp; File: <code>{meta_info.get('filename', 'Unknown')}</code> (Chunk {meta_info.get('chunk_index', 0)})
                        <div style="margin-top: 6px; color: #F1F5F9; font-size: 0.9rem;">{r.get('text', '')[:400]}...</div>
                    </div>
                    """)

        st.divider()

        # Document Management Table
        st.markdown("##### Indexed Document Vault")
        rag_documents = api_get("/api/rag/documents", [])

        if rag_documents and len(rag_documents) > 0:
            for doc in rag_documents:
                with st.container(border=True):
                    col_d1, col_d2 = st.columns([5, 1], vertical_alignment="center")
                    with col_d1:
                        proj_badge = f"<span class='aira-badge aira-badge-cyan'>📁 {doc.get('project_id')}</span>" if doc.get("project_id") else "<span class='aira-badge aira-badge-violet'>Global</span>"
                        st.html(f"<div><strong style='font-size: 1.05rem; color: #F8FAFC;'>{doc['filename']}</strong> &nbsp; {proj_badge}</div>")
                        st.caption(f"Type: `{doc.get('file_type', 'txt')}` &nbsp;•&nbsp; Chunks: `{doc.get('chunk_count', 0)}` &nbsp;•&nbsp; Size: `{doc.get('file_size', 0)} bytes` &nbsp;•&nbsp; ID: `{doc['id']}`")
                    with col_d2:
                        if st.button("Delete", key=f"del_doc_{doc['id']}", width="stretch", icon=":material/delete:"):
                            api_delete(f"/api/rag/documents/{doc['id']}")
                            st.rerun()
        else:
            st.info("No documents indexed yet. Upload notes or documentation above to ground responses.")

    with kb_tab_web:
        with st.container(border=True):
            st.markdown("##### :material/travel_explore: Live Internet Research Engine")
            st.caption("Multi-query search, readable page fetching, SSRF filtering, and contradiction analysis.")

            if st.session_state.privacy_mode == "local_only":
                st.warning("🔒 Internet Research is blocked because Local-Only Privacy Mode is active. Switch to Standard in Settings to run web research.", icon=":material/lock:")
            else:
                col_wq, col_wbtn = st.columns([3, 1], vertical_alignment="bottom")
                with col_wq:
                    web_query_input = st.text_input(
                        "Research Topic / Query",
                        placeholder="e.g. Latest advancements in Faster-Whisper on Apple Silicon",
                        key="kb_web_query_input"
                    )
                with col_wbtn:
                    btn_run_research = st.button("Run Research", width="stretch", icon=":material/search:")

                if btn_run_research and web_query_input.strip():
                    with st.spinner("Conducting grounded web research & analyzing contradictions..."):
                        status_c, res_data = api_post("/api/knowledge/research", {
                            "query": web_query_input.strip(),
                            "privacy_mode": st.session_state.privacy_mode,
                            "max_results": 4
                        })
                        if status_c == 200:
                            st.session_state.last_web_research_result = res_data
                        else:
                            st.error(f"Research failed ({status_c}): {res_data.get('detail', 'Unknown error')}")

                if "last_web_research_result" in st.session_state and st.session_state.last_web_research_result:
                    w_res = st.session_state.last_web_research_result
                    results = w_res.get("results", [])
                    contradictions = w_res.get("contradictions", [])

                    if contradictions:
                        st.markdown("###### :material/warning: Cross-Source Contradictions Detected")
                        for c in contradictions:
                            st.warning(c)

                    st.markdown(f"###### Grounded Web Sources ({len(results)} found)")
                    for idx, src in enumerate(results):
                        with st.container(border=True):
                            st.markdown(f"**[{src.get('title', 'Source')}]({src.get('url')})**")
                            st.caption(f"Retrieved: `{src.get('retrieved_at', '')[:19]}` • Snippet length: {len(src.get('snippet', ''))} chars")
                            st.markdown(f"> {src.get('snippet', '')}")
                            if src.get("full_content"):
                                with st.expander("View Extracted Readable Page Content"):
                                    st.text(src["full_content"][:1000] + ("..." if len(src["full_content"]) > 1000 else ""))


# ==============================================================================
# SECTION 4: MEMORY & PREFERENCES WORKSPACE
# ==============================================================================
elif st.session_state.active_section == "Memory & Preferences":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">Personal Memory & Learned Preferences</div>
            <div class="aira-workspace-subtitle">Inspect, refine, or remove information AIRA has learned through real interaction.</div>
        </div>
    </div>
    """)

    mem_tab1, mem_tab2, mem_tab3, mem_tab4, mem_tab5 = st.tabs([
        "👤 Personal Profile",
        "💡 Behavioral Preferences",
        "📖 Episodic Interactions",
        "⚙️ Procedural Knowledge",
        "💾 Memory Export",
    ])

    with mem_tab1:
        st.markdown("##### Explicit Profile Attributes")
        st.caption("Factual attributes configured by you or confirmed during conversation.")

        profile_dict = api_get("/api/memory?category=profile", {})

        col_pr1, col_pr2 = st.columns([1, 1])
        with col_pr1:
            with st.container(border=True):
                st.markdown("**Current Stored Attributes**")
                display_name_val = profile_dict.get("preferred_name") or user_display_name
                st.markdown(f"**Preferred Name:** {display_name_val if display_name_val else '*Not specified yet*'}")
                st.markdown(f"**Communication Style:** {profile_dict.get('communication_style') or '*Adaptive default*'}")
                st.markdown(f"**Primary Interests:** {profile_dict.get('primary_interests') or '*Not configured*'}")
                st.markdown(f"**Technical Background:** {profile_dict.get('technical_background') or '*General / Not specified*'}")
                st.markdown(f"**Active Learning Goals:** {profile_dict.get('learning_goals') or '*None specified*'}")

        with col_pr2:
            with st.container(border=True):
                st.markdown("**Update Profile Attribute**")
                with st.form("form_update_profile"):
                    attr_field = st.selectbox(
                        "Attribute",
                        ["preferred_name", "communication_style", "primary_interests", "technical_background", "learning_goals"],
                        format_func=lambda x: x.replace("_", " ").title(),
                    )
                    attr_val = st.text_input("New Value")
                    submitted_attr = st.form_submit_button("Save Attribute", width="stretch")
                    if submitted_attr and attr_val.strip():
                        if attr_field == "preferred_name":
                            api_post("/api/user-profile/name", {"name": attr_val.strip()})
                        api_post("/api/memory", {"key": attr_field, "value": attr_val.strip()})
                        st.success(f"Updated {attr_field.replace('_', ' ').title()}.")
                        st.rerun()

                if user_display_name:
                    if st.button("Reset User Name", width="content"):
                        api_delete("/api/user-profile/name")
                        st.info("User name cleared.")
                        st.rerun()

    with mem_tab2:
        st.markdown("##### Inferred & Confirmed Preferences")
        st.caption("Preferences inferred from interaction evidence remain candidates until verified.")

        pref_list = api_get("/api/memory?category=preferences", [])
        if pref_list and len(pref_list) > 0:
            for p in pref_list:
                with st.container(border=True):
                    col_pf1, col_pf2 = st.columns([4, 1], vertical_alignment="center")
                    with col_pf1:
                        badge_html = '<span class="aira-badge aira-badge-green">● Confirmed</span>' if p.get("user_approved") else '<span class="aira-badge aira-badge-amber">● Candidate (Inferred)</span>'
                        st.html(f"<div><strong style='font-size: 1.05rem; color: #F8FAFC;'>{p['preference_key']}</strong> &nbsp; {badge_html}</div>")
                        st.markdown(f"**Preference Value:** {p['preference_value']}")
                        if p.get("supporting_observations"):
                            st.caption(f"Supporting Evidence: {p['supporting_observations']}")

                    with col_pf2:
                        if not p.get("user_approved"):
                            if st.button("Confirm", key=f"appr_btn_{p['id']}", width="stretch"):
                                api_post(f"/api/preferences/{p['id']}/approve", {})
                                st.rerun()
                        if st.button("Remove", key=f"del_pref_btn_{p['id']}", width="stretch"):
                            api_delete(f"/api/memory/preferences/{p['id']}")
                            st.rerun()
        else:
            st.info("No behavioral preferences recorded yet. They will emerge naturally through conversation.")

    with mem_tab3:
        st.markdown("##### Significant Episodic Interactions")
        st.caption("Key conversation summaries, milestone decisions, and learning moments.")

        episodic_records = api_get("/api/memory?category=episodic", [])
        if episodic_records and len(episodic_records) > 0:
            for ep in episodic_records[:12]:
                with st.container(border=True):
                    col_ep1, col_ep2 = st.columns([5, 1])
                    with col_ep1:
                        ep_title = ep.get("title") or "Untitled"
                        ep_type = str(ep.get("event_type") or "task_outcome").title()
                        st.markdown(f"**{ep_title}** &nbsp;•&nbsp; :grey[{ep_type}]")
                        st.markdown(ep["content"])
                        st.caption(f"Recorded: {ep['created_at'][:19]}")
                    with col_ep2:
                        if st.button("Delete", key=f"del_ep_btn_{ep['id']}", width="stretch"):
                            api_delete(f"/api/memory/episodic/{ep['id']}")
                            st.rerun()
        else:
            st.info("No episodic memories stored yet.")

    with mem_tab4:
        st.markdown("##### Procedural Knowledge & Workflows")
        st.caption("Habitual workflows, specialized instructions, and recurring tasks.")

        procedural_records = api_get("/api/memory?category=procedural", [])
        if procedural_records and len(procedural_records) > 0:
            for proc in procedural_records:
                with st.container(border=True):
                    st.markdown(f"**{proc['workflow_name']}**")
                    st.markdown(proc["steps"])
                    if st.button("Delete Workflow", key=f"del_proc_{proc['id']}"):
                        api_delete(f"/api/memory/procedural/{proc['id']}")
                        st.rerun()
        else:
            st.info("No procedural workflows indexed yet.")

    with mem_tab5:
        st.markdown("##### Export Memory Vault")
        st.caption("Download an encrypted or portable JSON copy of all personal memory stores.")

        export_data = api_get("/api/memory?category=export", {})
        st.download_button(
            label="Download Complete Memory Vault (JSON)",
            data=json.dumps(export_data, indent=2),
            file_name="aira_memory_vault.json",
            mime="application/json",
            icon=":material/download:",
            width="content",
        )


# ==============================================================================
# SECTION 5: SETTINGS & ADVANCED CONTROLS
# ==============================================================================
elif st.session_state.active_section == "Settings":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">Settings & Operational Controls</div>
            <div class="aira-workspace-subtitle">Configure security boundaries, audio personas, runtime telemetry, and constitutional safeguards.</div>
        </div>
    </div>
    """)

    set_tab_sec, set_tab_voice, set_tab_diag, set_tab_safe = st.tabs([
        "🔒 Security & Privacy",
        "🎙️ Voice & Audio Settings",
        "💻 System & Diagnostics",
        "🛡️ Constitutional Safeguards",
    ])

    # 1. Security & Privacy Tab
    with set_tab_sec:
        with st.container(border=True):
            st.markdown("##### :material/shield: Operational Privacy Mode")
            st.caption("Control whether requests can be routed to cloud models (Nemotron-3) or are restricted to local on-device Gemma.")

            is_local = (st.session_state.privacy_mode == "local_only")
            new_local = st.toggle(
                "Local-Only Privacy Mode",
                value=is_local,
                help="When enabled, zero data leaves this device. All inference runs locally via Ollama / Gemma."
            )
            st.session_state.privacy_mode = "local_only" if new_local else "standard"

            if new_local:
                st.success("🔒 Strict Local Privacy Active: External APIs, web research, and cloud engines are disabled.")
            else:
                st.info("🌐 Standard Hybrid Mode Active: Complex reasoning is routed to cloud Nemotron; quick conversational queries run on local Gemma.")

            st.divider()

            st.markdown("##### :material/bug_report: Execution & Telemetry Traces")
            st.session_state.show_debug_traces = st.toggle(
                "Show Engine Routing & Latency Traces in Chat",
                value=st.session_state.show_debug_traces,
                help="Displays exact model IDs, latency timings, and tool arguments below each assistant message."
            )

    # 2. Voice & Audio Settings Tab
    with set_tab_voice:
        with st.container(border=True):
            st.markdown("##### :material/volume_up: Spoken Responses (TTS)")
            st.session_state.voice_output_enabled = st.toggle(
                "Enable Speech Generation",
                value=st.session_state.voice_output_enabled,
                help="Synthesizes voice audio for assistant answers."
            )

            st.divider()

            st.markdown("##### :material/mic: Speech Recognition & Voice Personas")
            st.session_state.selected_language = st.selectbox(
                "Speech Recognition Language",
                options=["auto", "en", "hi", "mr"],
                format_func=lambda x: {
                    "auto": "🌐 Auto-Detect Language",
                    "en": "🇬🇧 English",
                    "hi": "🇮🇳 Hindi (हिंदी)",
                    "mr": "🇮🇳 Marathi (मराठी)",
                }.get(x, x),
                index=["auto", "en", "hi", "mr"].index(st.session_state.selected_language),
                help="Configures Faster-Whisper model language mode.",
                key="settings_speech_lang_select"
            )

            voice_cfg = api_get("/api/voice/config", {"available_voices": [{"id": "Samantha", "name": "Samantha (US Female)"}]})
            avail_voices = voice_cfg.get("available_voices", [])
            voice_ids = [v["id"] for v in avail_voices] if avail_voices else ["Samantha"]
            curr_v_idx = voice_ids.index(st.session_state.selected_voice) if st.session_state.selected_voice in voice_ids else 0
            st.session_state.selected_voice = st.selectbox(
                "Voice Persona",
                options=voice_ids,
                format_func=lambda vid: next((v["name"] for v in avail_voices if v["id"] == vid), vid),
                index=curr_v_idx,
                help="Select synthetic voice persona for spoken replies.",
                key="settings_voice_select"
            )

            st.divider()

            st.markdown("##### :material/record_voice_over: Hands-Free Wake-Word Detection")
            wake_sett = st.toggle(
                "Listen for 'Hey AIRA'",
                value=st.session_state.wake_word_enabled,
                help="Local on-device listener for the 'Hey AIRA' wake phrase.",
                key="settings_wake_word_toggle"
            )
            if wake_sett != st.session_state.wake_word_enabled:
                st.session_state.wake_word_enabled = wake_sett
                st.session_state.wake_word_state = "listening_locally" if wake_sett else "wake_word_disabled"
                st.rerun()

            st.caption("Wake Phrase: `'Hey AIRA'` • Hardware: `Default Microphone` • Engine: `Local Faster-Whisper`")

    # 3. System & Diagnostics Tab
    with set_tab_diag:
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            with st.container(border=True):
                st.markdown("**FastAPI Backend**")
                if is_healthy:
                    st.html('<span class="aira-badge aira-badge-green">● HEALTHY</span>')
                else:
                    st.html('<span class="aira-badge aira-badge-amber">● OFFLINE</span>')
                st.caption(f"Port 8080 • v{health_data.get('version', '1.0.0')}")

        with col_m2:
            with st.container(border=True):
                st.markdown("**Local Engine**")
                if local_engine_online:
                    st.html('<span class="aira-badge aira-badge-green">● ACTIVE</span>')
                else:
                    st.html('<span class="aira-badge aira-badge-amber">● STANDBY</span>')
                st.caption("Gemma 2B • Ollama")

        with col_m3:
            with st.container(border=True):
                st.markdown("**Cloud Engine**")
                if cloud_engine_online:
                    st.html('<span class="aira-badge aira-badge-cyan">● CONNECTED</span>')
                else:
                    st.html('<span class="aira-badge aira-badge-amber">● OFFLINE</span>')
                st.caption("Nemotron-70B • OpenRouter")

        with col_m4:
            with st.container(border=True):
                st.markdown("**Persistent DB**")
                st.html('<span class="aira-badge aira-badge-violet">● INITIALIZED</span>')
                st.caption("SQLite + RAG Index")

        st.divider()

        # Feedback Quality Metrics
        st.markdown("##### Feedback & Quality Metrics")
        fb_stats = api_get("/api/feedback/metrics", {})
        col_fb1, col_fb2, col_fb3 = st.columns(3)
        col_fb1.metric("Responses Rated", fb_stats.get("total_responses_rated", 0))
        pos_rate = fb_stats.get("positive_rate", 1.0) * 100
        col_fb2.metric("Helpful Rate", f"{pos_rate:.1f}%")
        col_fb3.metric("Issues Reported", fb_stats.get("negative_count", 0))

        st.divider()

        # Automated Benchmark Verification Suite
        st.markdown("##### Automated Verification Benchmark Suite")
        st.caption("Executes standard test queries across intent routing, boundary safety, and tool delegation.")

        if st.button("Run Verification Suite", width="content", icon=":material/play_circle:"):
            with st.spinner("Executing benchmark evaluation suite..."):
                status_code, bench_report = api_post("/api/evaluation/run", {})
                if status_code == 200:
                    acc = bench_report.get("accuracy_pct", 0)
                    st.success(f"Benchmark Complete! Accuracy Score: **{acc}%**")

                    results_list = bench_report.get("results", [])
                    for br in results_list:
                        passed = br.get("passed", False)
                        icon = "✅" if passed else "❌"
                        st.markdown(f"{icon} `{br.get('id')}` ({br.get('category')}) — {br.get('details')}")
                else:
                    st.error("Benchmark execution encountered an error.")

    # 4. Constitutional Safeguards Tab
    with set_tab_safe:
        st.markdown("##### The Seven Principles of AIRA")
        constitution_data = api_get("/api/constitution", {})
        principles = constitution_data.get("principles", [])

        col_c1, col_c2 = st.columns([3, 2])
        with col_c1:
            for p in principles:
                with st.container(border=True):
                    st.markdown(f"**Principle {p['id']}: {p['name']}**")
                    st.markdown(p["statement"])
                    st.html(f"<div style='font-size: 0.78rem; color: #94A3B8; margin-top: 4px;'><strong>Enforcement:</strong> <code>{p['enforcement']}</code></div>")

        with col_c2:
            with st.container(border=True):
                st.markdown("##### Active Safeguard Layers")
                for sf in constitution_data.get("active_safeguards", []):
                    st.markdown(f"- ✅ **{sf}**")

                st.divider()
                st.markdown("**Constitution Integrity**")
                st.caption(f"Version: `{constitution_data.get('version', '1.0.0')}`")
                st.caption("Immutable runtime policy: Execution engine validates every tool action prior to invocation.")

        st.divider()

        st.markdown("##### Security Audit Trail")
        st.caption("Chronological record of tool decisions, policy checks, and boundary enforcements.")

        audit_logs = api_get("/api/audit-logs", [])
        if audit_logs and len(audit_logs) > 0:
            log_records = []
            for al in audit_logs[:40]:
                log_records.append({
                    "Timestamp": al.get("timestamp", "")[:19],
                    "Action / Tool": al.get("tool_name") or al.get("action", "unknown"),
                    "Risk Level": str(al.get("risk_level") or "low").upper(),
                    "Decision": "ALLOWED" if al.get("allowed", True) else "BLOCKED",
                    "Details": al.get("reason") or str(al.get("parameters", ""))[:50],
                })
            st.dataframe(log_records, width="stretch", hide_index=True)
        else:
            st.info("No audit entries recorded yet.")
