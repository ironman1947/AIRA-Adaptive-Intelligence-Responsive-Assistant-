"""PROJECT AIRA — Adaptive Intelligence & Responsive Assistant

Premium Personal AI Workspace & Multi-Agent Interface.
"""

import os
import json
import time
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
import requests
import streamlit as st

BACKEND_URL = os.getenv("AIRA_BACKEND_URL", "http://localhost:8080")

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
}

/* Hide Default Streamlit Header Decoration for Clean Look */
header[data-testid="stHeader"] {
    background: transparent;
}

/* Luminous Orb Visual */
.aira-orb-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2.2rem 1rem 1.4rem 1rem;
    text-align: center;
}

.aira-orb {
    width: 88px;
    height: 88px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #00F0FF 0%, #3B82F6 40%, #8B5CF6 75%, #070A12 100%);
    box-shadow: 0 0 35px rgba(0, 240, 255, 0.45), 0 0 70px rgba(139, 92, 246, 0.25);
    animation: aira-pulse 4.5s ease-in-out infinite alternate;
    position: relative;
    margin-bottom: 1.2rem;
}

.aira-orb::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 108px;
    height: 108px;
    border-radius: 50%;
    border: 1px dashed rgba(0, 240, 255, 0.35);
    animation: aira-ring-spin 18s linear infinite;
}

@keyframes aira-pulse {
    0% {
        transform: scale(0.95);
        box-shadow: 0 0 25px rgba(0, 240, 255, 0.35), 0 0 50px rgba(139, 92, 246, 0.2);
    }
    100% {
        transform: scale(1.04);
        box-shadow: 0 0 45px rgba(0, 240, 255, 0.65), 0 0 90px rgba(139, 92, 246, 0.4);
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

/* Sidebar Brand Pill */
.aira-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0.6rem 0.2rem 1.2rem 0.2rem;
    border-bottom: 1px solid rgba(30, 41, 59, 0.7);
    margin-bottom: 1.2rem;
}

.aira-mini-orb {
    width: 32px;
    height: 32px;
    min-width: 32px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #00F0FF 0%, #3B82F6 45%, #8B5CF6 85%);
    box-shadow: 0 0 15px rgba(0, 240, 255, 0.5);
}

.aira-sidebar-title {
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #F8FAFC;
    line-height: 1.2;
}

.aira-sidebar-sub {
    font-size: 0.72rem;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Custom Cards */
.aira-glass-card {
    background: rgba(15, 22, 38, 0.65);
    border: 1px solid rgba(0, 240, 255, 0.12);
    border-radius: 12px;
    padding: 1.2rem;
    margin-bottom: 0.9rem;
    backdrop-filter: blur(10px);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.aira-glass-card:hover {
    border-color: rgba(0, 240, 255, 0.3);
    box-shadow: 0 4px 20px rgba(0, 240, 255, 0.06);
}

.aira-citation-card {
    background: rgba(13, 19, 33, 0.75);
    border-left: 3px solid #00F0FF;
    border-radius: 4px 8px 8px 4px;
    padding: 0.6rem 0.9rem;
    margin-top: 0.6rem;
    font-size: 0.85rem;
    color: #CBD5E1;
}

/* Status Badges */
.aira-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 0.72rem;
    font-weight: 600;
}
.aira-badge-cyan {
    background: rgba(0, 240, 255, 0.1);
    color: #00F0FF;
    border: 1px solid rgba(0, 240, 255, 0.25);
}
.aira-badge-violet {
    background: rgba(139, 92, 246, 0.12);
    color: #C084FC;
    border: 1px solid rgba(139, 92, 246, 0.28);
}
.aira-badge-green {
    background: rgba(34, 197, 94, 0.12);
    color: #4ADE80;
    border: 1px solid rgba(34, 197, 94, 0.25);
}
.aira-badge-amber {
    background: rgba(245, 158, 11, 0.12);
    color: #FBBF24;
    border: 1px solid rgba(245, 158, 11, 0.25);
}

/* Subtle Workspace Header */
.aira-workspace-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0 1.2rem 0;
    border-bottom: 1px solid rgba(30, 41, 59, 0.5);
    margin-bottom: 1.2rem;
}

.aira-workspace-title {
    font-size: 1.35rem;
    font-weight: 700;
    color: #F1F5F9;
    letter-spacing: -0.01em;
}

.aira-workspace-subtitle {
    font-size: 0.85rem;
    color: #94A3B8;
}
</style>
"""

st.html(CUSTOM_CSS)

# ------------------------------------------------------------------------------
# Session State Initialization
# ------------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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

if "pending_voice_transcript" not in st.session_state:
    st.session_state.pending_voice_transcript = None

if "last_processed_audio_bytes_hash" not in st.session_state:
    st.session_state.last_processed_audio_bytes_hash = None

if "last_transcription_meta" not in st.session_state:
    st.session_state.last_transcription_meta = None

if "audio_cache_by_req_id" not in st.session_state:
    st.session_state.audio_cache_by_req_id = {}

# ------------------------------------------------------------------------------
# API Helpers
# ------------------------------------------------------------------------------
def api_get(endpoint: str, default=None):
    try:
        resp = requests.get(f"{BACKEND_URL}{endpoint}", timeout=4.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return default

def api_post(endpoint: str, payload: dict, timeout: float = 60.0):
    try:
        resp = requests.post(f"{BACKEND_URL}{endpoint}", json=payload, timeout=timeout)
        return resp.status_code, resp.json()
    except Exception as e:
        return 500, {"error": str(e)}

def api_voice_stop():
    """Cancels active speech output and stops macOS say processes immediately."""
    try:
        requests.post(f"{BACKEND_URL}/api/voice/stop", timeout=2.0)
    except Exception:
        pass

def api_delete(endpoint: str, timeout: float = 10.0):
    try:
        resp = requests.delete(f"{BACKEND_URL}{endpoint}", timeout=timeout)
        return resp.status_code, resp.json()
    except Exception as e:
        return 500, {"error": str(e)}

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
        resp = requests.post(f"{BACKEND_URL}/api/voice/transcribe", files=files, data=data, timeout=35.0)
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
        resp = requests.post(f"{BACKEND_URL}/api/voice/synthesize", json=payload, timeout=25.0)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print(f"TTS synthesis API error: {e}")
    return None

# ------------------------------------------------------------------------------
# Cached / Live Data Fetching
# ------------------------------------------------------------------------------
health_data = api_get("/health", {})
is_healthy = health_data.get("status") == "healthy"
local_engine_online = health_data.get("local_engine_online", False)
cloud_engine_online = health_data.get("cloud_engine_online", False)

user_info = api_get("/api/user-profile/name", {})
user_display_name = user_info.get("user_display_name")

# ------------------------------------------------------------------------------
# SIDEBAR: Branding, Workspaces, and Controls
# ------------------------------------------------------------------------------
with st.sidebar:
    # AIRA Distinctive Brand Header
    st.html("""
    <div class="aira-sidebar-brand">
        <div class="aira-mini-orb"></div>
        <div>
            <div class="aira-sidebar-title">AIRA</div>
            <div class="aira-sidebar-sub">Adaptive Intelligence</div>
        </div>
    </div>
    """)

    # Workspace Section Navigation
    SECTIONS = [
        ("Conversation", ":material/chat:"),
        ("Memory & Preferences", ":material/psychology:"),
        ("Projects", ":material/folder:"),
        ("Knowledge Base", ":material/menu_book:"),
        ("Safeguards", ":material/security:"),
        ("System & Diagnostics", ":material/monitoring:"),
    ]

    section_labels = [f"{icon}  {name}" for name, icon in SECTIONS]
    section_name_map = {f"{icon}  {name}": name for name, icon in SECTIONS}
    
    current_idx = 0
    for idx, (s_name, _) in enumerate(SECTIONS):
        if s_name == st.session_state.active_section:
            current_idx = idx
            break

    selected_label = st.radio(
        "Workspace Navigation",
        options=section_labels,
        index=current_idx,
        label_visibility="collapsed",
        key="sidebar_navigation_radio",
    )
    st.session_state.active_section = section_name_map[selected_label]

    st.divider()

    # Workspace Context (Project Selector)
    st.markdown("**Workspace Context**")
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
        help="Ground conversations and document ingestion in a dedicated project workspace."
    )
    st.session_state.active_project = None if selected_proj == "none" else selected_proj

    # Privacy & Control Toggles
    with st.container(border=True):
        st.markdown("**Security & Telemetry**")
        local_toggle = st.toggle(
            "Local-only privacy",
            value=(st.session_state.privacy_mode == "local_only"),
            help="Strictly blocks cloud routing. All reasoning executes locally on Gemma 2B.",
        )
        st.session_state.privacy_mode = "local_only" if local_toggle else "standard"
        if local_toggle:
            st.caption(":green[🔒 Zero cloud telemetry active.]")

        st.session_state.show_debug_traces = st.toggle(
            "Execution traces",
            value=st.session_state.show_debug_traces,
            help="Reveal engine routing, tool parameters, and timing in conversation.",
        )

    # Voice & Desktop Control Section
    with st.container(border=True):
        st.markdown("**Voice & Desktop Control**")
        st.session_state.voice_output_enabled = st.toggle(
            "Spoken responses (TTS)",
            value=st.session_state.voice_output_enabled,
            help="AIRA speaks responses aloud using macOS native speech synthesis.",
        )

        wake_sb = st.toggle(
            "Enable wake word ('Hey AIRA')",
            value=st.session_state.wake_word_enabled,
            help="Listen locally for 'Hey AIRA' wake phrase.",
            key="sidebar_wake_toggle",
        )
        if wake_sb != st.session_state.wake_word_enabled:
            st.session_state.wake_word_enabled = wake_sb
            st.session_state.wake_word_state = "listening_locally" if wake_sb else "wake_word_disabled"
            st.rerun()

        st.caption("Wake Phrase: `:material/mic: 'Hey AIRA'` • Mic: `Default CoreAudio`")

        st.session_state.selected_language = st.selectbox(
            "Speech Language",
            options=["auto", "en", "hi", "mr"],
            format_func=lambda x: {
                "auto": "🌐 Auto-Detect Language",
                "en": "🇬🇧 English",
                "hi": "🇮🇳 Hindi (हिंदी)",
                "mr": "🇮🇳 Marathi (मराठी)",
            }.get(x, x),
            index=["auto", "en", "hi", "mr"].index(st.session_state.selected_language),
            help="Configures speech recognition model for English, Hindi, Marathi, or mixed code-switching.",
            key="sidebar_speech_lang_select"
        )

        voice_cfg = api_get("/api/voice/config", {"available_voices": [{"id": "Samantha", "name": "Samantha (US Female)"}]})
        avail_voices = voice_cfg.get("available_voices", [])
        voice_ids = [v["id"] for v in avail_voices] if avail_voices else ["Samantha"]
        curr_v_idx = voice_ids.index(st.session_state.selected_voice) if st.session_state.selected_voice in voice_ids else 0
        st.session_state.selected_voice = st.selectbox(
            "AIRA Voice",
            options=voice_ids,
            format_func=lambda vid: next((v["name"] for v in avail_voices if v["id"] == vid), vid),
            index=curr_v_idx,
            help="Select native macOS voice persona (e.g. Samantha for English, Lekha for Hindi/Marathi).",
            key="sidebar_voice_select"
        )

        # Desktop Control Scopes
        desktop_stat = api_get("/api/desktop/status", {})
        pending_plans = desktop_stat.get("pending_plans", [])
        if pending_plans:
            st.warning(f"⚠️ **{len(pending_plans)} Pending Approval(s)**")
        else:
            st.caption("Computer Control: `Whitelisted Apps Only` • `Approval Required`")

    # Session Management
    col_sb1, col_sb2 = st.columns(2)
    with col_sb1:
        if st.button("New session", width="stretch", icon=":material/add:"):
            st.session_state.session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            st.session_state.messages = []
            st.session_state.pending_prompt = None
            st.rerun()
    with col_sb2:
        if st.button("Clear chat", width="stretch", icon=":material/delete_sweep:"):
            api_delete(f"/api/history/{st.session_state.session_id}")
            st.session_state.messages = []
            st.session_state.pending_prompt = None
            st.rerun()

    st.divider()

    # Dynamic Runtime Status
    st.markdown("**Runtime Status**")
    if is_healthy:
        status_dot = '<span class="aira-badge aira-badge-green">● Online & Ready</span>'
    else:
        status_dot = '<span class="aira-badge aira-badge-amber">● Connecting / Offline</span>'

    local_tag = "Ready" if local_engine_online else "Standby"
    cloud_tag = "Connected" if cloud_engine_online else "Offline"

    st.html(f"""
    <div style="font-size: 0.8rem; line-height: 1.6; color: #94A3B8;">
        <div>System: {status_dot}</div>
        <div style="margin-top: 4px;">Local Gemma: <strong style="color: #F1F5F9;">{local_tag}</strong></div>
        <div>Cloud Nemotron: <strong style="color: #F1F5F9;">{cloud_tag}</strong></div>
        <div style="margin-top: 4px; font-size: 0.72rem; color: #64748B;">User: <strong style="color: #CBD5E1;">{user_display_name or 'Unregistered'}</strong></div>
    </div>
    """)


# ==============================================================================
# SECTION 1: CONVERSATION WORKSPACE (Primary Experience)
# ==============================================================================
if st.session_state.active_section == "Conversation":
    # Workspace Top Context Bar
    proj_tag = f"📁 {st.session_state.active_project}" if st.session_state.active_project else "General Workspace"
    privacy_tag = "🔒 Local Privacy" if st.session_state.privacy_mode == "local_only" else "🌐 Hybrid Dual-Engine"

    col_h1, col_h2 = st.columns([3, 1], vertical_alignment="center")
    with col_h1:
        st.html(f"""
        <div class="aira-workspace-header" style="border-bottom: none; padding-bottom: 0;">
            <div>
                <div class="aira-workspace-title">Personal AI Workspace</div>
                <div class="aira-workspace-subtitle">{proj_tag} &nbsp;•&nbsp; {privacy_tag}</div>
            </div>
        </div>
        """)
    with col_h2:
        st.caption(f"Session: `{st.session_state.session_id[-11:]}`")

    # --------------------------------------------------------------------------
    # Voice & Desktop Control Bar (Compact Hands-Free & Safety Controls)
    # --------------------------------------------------------------------------
    with st.container():
        col_ctl1, col_ctl2, col_ctl3 = st.columns([2, 3, 1], vertical_alignment="center")
        with col_ctl1:
            wake_toggle = st.toggle(
                "🎙️ Hands-Free 'Hey AIRA'",
                value=st.session_state.wake_word_enabled,
                help="Enable continuous local on-device wake-word detection for 'Hey AIRA'. Zero cloud ambient streaming.",
                key="toggle_wake_word_active"
            )
            if wake_toggle != st.session_state.wake_word_enabled:
                st.session_state.wake_word_enabled = wake_toggle
                st.session_state.wake_word_state = "listening_locally" if wake_toggle else "wake_word_disabled"
                st.rerun()

        with col_ctl2:
            # Lifecycle state pill
            if st.session_state.wake_word_enabled:
                st.html("""
                <span class="aira-badge aira-badge-cyan">● Listening Locally for 'Hey AIRA'</span>
                <span style="font-size: 0.75rem; color: #94A3B8; margin-left: 8px;">100% On-Device • Local Faster-Whisper</span>
                """)
            else:
                st.html("""
                <span class="aira-badge" style="background: rgba(100, 116, 139, 0.2); color: #94A3B8; border: 1px solid rgba(100, 116, 139, 0.4);">○ Wake Word Disabled</span>
                <span style="font-size: 0.75rem; color: #64748B; margin-left: 8px;">Click 🎙️ in composer to dictate</span>
                """)

        with col_ctl3:
            if st.button("⏹️ Stop", key="btn_emergency_stop_header", help="Emergency Stop: halts ongoing speech playback and cancels tasks", width="stretch"):
                api_voice_stop()
                st.toast("Speech and active audio playback halted.", icon="⏹️")

    st.divider()

    # Initial Welcoming Empty State
    if len(st.session_state.messages) == 0:
        greeting_target = f", {user_display_name}" if user_display_name else ""
        st.html(f"""
        <div class="aira-orb-container">
            <div class="aira-orb"></div>
            <h2 style="font-size: 1.65rem; font-weight: 700; color: #F8FAFC; margin-bottom: 0.4rem; letter-spacing: -0.02em;">
                Greetings{greeting_target}.
            </h2>
            <p style="font-size: 0.96rem; color: #94A3B8; max-width: 540px; margin-bottom: 1.5rem; line-height: 1.5;">
                I'm <strong style="color: #00F0FF;">AIRA</strong>, your adaptive intelligence coworker and personal assistant.
                How can we collaborate today?
            </p>
        </div>
        """)

        # 4 Functional Suggested Prompts
        st.markdown("<p style='text-align: center; font-size: 0.82rem; color: #64748B; margin-bottom: 0.8rem;'>SUGGESTED COLLABORATIONS</p>", unsafe_allow_html=True)
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

    # Render Conversation Messages
    for idx, msg in enumerate(st.session_state.messages):
        role = msg["role"]
        is_assistant = (role == "assistant")
        avatar_val = ":material/auto_awesome:" if is_assistant else None

        with st.chat_message(role, avatar=avatar_val):
            # Compact unobtrusive model tag
            if is_assistant and msg.get("meta"):
                if st.session_state.show_debug_traces:
                    st.caption(msg["meta"])
                else:
                    # Subtle model pill
                    engine_label = "Local Gemma 2B" if "gemma" in msg.get("meta", "").lower() else "Cloud Nemotron"
                    if msg.get("tools_triggered"):
                        engine_label += " • Tool Assisted"
                    st.caption(f":grey[{engine_label}]")

            # Tool Execution Expander if debug traces enabled or tools executed
            if is_assistant and msg.get("executed_tools") and len(msg["executed_tools"]) > 0:
                with st.expander(f":material/build: Executed {len(msg['executed_tools'])} Tool Action(s)", expanded=False):
                    for t in msg["executed_tools"]:
                        st.markdown(f"**Tool:** `{t['tool']}` &nbsp;|&nbsp; **Risk:** `{t.get('risk_level', 'low')}` &nbsp;|&nbsp; **Decision:** `{t.get('decision', 'allowed')}`")
                        if t.get("arguments"):
                            st.code(json.dumps(t["arguments"], indent=2), language="json")

            # Main Message Markdown Body
            st.markdown(msg["content"])

            # Grounded Sources Breakdown
            if msg.get("sources_used") and len(msg["sources_used"]) > 0:
                with st.expander(f":material/dataset: Grounded Evidence ({len(msg['sources_used'])} sources)", expanded=False):
                    for src in msg["sources_used"]:
                        st.markdown(f"- {src}")

            # Cross-Source Contradictions Warning
            if msg.get("contradictions") and len(msg["contradictions"]) > 0:
                for c in msg["contradictions"]:
                    st.warning(f"Discrepancy noted across sources: {c}", icon=":material/warning:")

            # Clean Citations Display
            if msg.get("citations") and len(msg["citations"]) > 0:
                with st.container():
                    st.markdown("##### :material/link: Grounded Sources & Citations")
                    for cite in msg["citations"]:
                        st.markdown(f"- {cite}")

            # Inline Action Plan Approval Card (If Computer Modification was proposed)
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
                        if st.button("✅ Approve & Apply Change", key=f"msg_appr_{idx}_{ap['id']}", width="stretch"):
                            st_code, res = api_post("/api/desktop/approve", {"approval_id": ap["id"], "approved": True})
                            msg["pending_approval"] = None
                            if st_code == 200:
                                st.success(f"Change applied: {res.get('outcome', 'Success')}")
                            else:
                                st.error(f"Execution error: {res.get('detail', 'Unknown error')}")
                            st.rerun()
                    with col_ap2:
                        if st.button("❌ Reject & Discard", key=f"msg_deny_{idx}_{ap['id']}", width="stretch"):
                            api_post("/api/desktop/approve", {"approval_id": ap["id"], "approved": False})
                            msg["pending_approval"] = None
                            st.warning("Action rejected. No modifications made.")
                            st.rerun()

            # Audio Playback & Interruption for Assistant Responses
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
                        if st.button("🔊 Listen", key=f"btn_listen_{idx}", help="Speak response aloud with natural feminine voice"):
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
                                    st.warning("Speech synthesis unavailable for this message.")
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
                            st.success("Correction saved. AIRA's verification memory updated.")
                            st.rerun()

    # --------------------------------------------------------------------------
    # Mandatory Approval Panel for Computer Modifications
    # --------------------------------------------------------------------------
    approvals_data = api_get("/api/approvals", [])
    active_pending = [a for a in approvals_data if a.get("status") == "pending"]
    if active_pending:
        for ap in active_pending:
            with st.container(border=True):
                st.warning("⚠️ **Proposed Computer Modification — Human Approval Required**", icon=":material/warning:")
                st.markdown(f"**Action:** `{ap['tool_name']}` &nbsp;|&nbsp; **Risk:** `{ap.get('risk_level', 'HIGH')}`")
                st.markdown(f"**Plan / Reason:** {ap.get('reason')}")
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
                    if st.button("✅ Approve & Apply Change", key=f"chat_appr_{ap['id']}", width="stretch"):
                        st_code, res = api_post("/api/desktop/approve", {"approval_id": ap["id"], "approved": True})
                        if st_code == 200:
                            st.success(f"Change applied: {res.get('outcome', 'Success')}")
                        else:
                            st.error(f"Execution error: {res.get('detail', 'Unknown error')}")
                        st.rerun()
                with col_ap2:
                    if st.button("❌ Reject & Discard", key=f"chat_deny_{ap['id']}", width="stretch"):
                        api_post("/api/desktop/approve", {"approval_id": ap["id"], "approved": False})
                        st.warning("Action rejected. No modifications were made to your computer.")
                        st.rerun()

    # --------------------------------------------------------------------------
    # Dictation Panel (Mode A: Click-to-Dictate into Chat Composer)
    # --------------------------------------------------------------------------
    if st.session_state.get("dictation_active", False):
        with st.container(border=True):
            col_d_info, col_d_cancel = st.columns([4, 1], vertical_alignment="center")
            with col_d_info:
                st.markdown("🔴 **Recording Dictation... Speak clearly, then click stop to transcribe.**")
                st.caption(f"Speech Language: `{st.session_state.selected_language.upper()}` • Populates text field without auto-submitting.")
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
                                recognized_speech = trans_data["text"].strip()
                                # Preserve any previously typed text in the draft
                                existing_text = st.session_state.get("chat_draft", "").strip()
                                updated_text = f"{existing_text} {recognized_speech}".strip() if existing_text else recognized_speech
                                st.session_state.chat_draft = updated_text
                                st.session_state.dictation_active = False
                                st.toast(f"Dictation transcribed: \"{recognized_speech}\"", icon="🎙️")
                                st.rerun()
                            else:
                                err_msg = trans_data.get("error") or "No clear speech detected."
                                st.warning(f"Voice recognition: {err_msg} You can retry or type below.")

    # --------------------------------------------------------------------------
    # Redesigned Inline Chat Composer: [ Message AIRA... ] [ Mic ] [ Send ]
    # --------------------------------------------------------------------------
    with st.container():
        col_comp_text, col_comp_mic, col_comp_send = st.columns([10, 1, 1], vertical_alignment="bottom")
        with col_comp_text:
            typed_message = st.text_input(
                "Message AIRA...",
                value=st.session_state.get("chat_draft", ""),
                placeholder="Message AIRA, explore ideas, or automate Mac...",
                key="aira_composer_text_input",
                label_visibility="collapsed",
            )
            # Sync user typing to draft session state
            if typed_message != st.session_state.get("chat_draft", ""):
                st.session_state.chat_draft = typed_message

        with col_comp_mic:
            mic_label = "🔴" if st.session_state.get("dictation_active", False) else "🎙️"
            if st.button(mic_label, key="btn_composer_dictate_mic", help="Click to dictate speech into text field", width="stretch"):
                st.session_state.dictation_active = not st.session_state.get("dictation_active", False)
                st.rerun()

        with col_comp_send:
            send_clicked = st.button("🚀", key="btn_composer_send_msg", help="Send message to AIRA", width="stretch")

    # Resolve Prompt to Send
    prompt_to_send = None
    if send_clicked and st.session_state.get("chat_draft", "").strip():
        prompt_to_send = st.session_state.chat_draft.strip()
        st.session_state.chat_draft = ""
    elif st.session_state.pending_prompt:
        prompt_to_send = st.session_state.pending_prompt
        st.session_state.pending_prompt = None

    if prompt_to_send:
        # Append User Message
        st.session_state.messages.append({"role": "user", "content": prompt_to_send})
        with st.chat_message("user"):
            st.markdown(prompt_to_send)

        # Execute Backend Query
        with st.chat_message("assistant", avatar=":material/auto_awesome:"):
            with st.status(":shimmer[AIRA is thinking...]", type="compact") as status_box:
                payload = {
                    "prompt": prompt_to_send,
                    "session_id": st.session_state.session_id,
                    "project_id": st.session_state.active_project,
                    "privacy_mode": st.session_state.privacy_mode,
                }
                status_code, response = api_post("/api/chat", payload)

                if status_code == 200:
                    model = response.get("model_used", "Local/Cloud")
                    complexity = response.get("complexity", "standard")
                    tools_used = response.get("tools_triggered", False)
                    executed_tools = response.get("executed_tools", [])
                    citations = response.get("citations", [])
                    sources_used = response.get("sources_used", [])
                    contradictions = response.get("contradictions", [])
                    answer = response.get("result", "I have received your message.")
                    req_id = response.get("request_id", "")
                    reason = response.get("routing_reason", "")
                    category = response.get("intent_category", "conversation")

                    meta_desc = f"Engine: `{model}` ({complexity.title()} • {category.replace('_', ' ').title()})"
                    status_box.update(label=f"Responded via {model}", state="complete")

                    if st.session_state.show_debug_traces:
                        st.caption(meta_desc)
                    else:
                        engine_badge = "Local Gemma 2B" if "gemma" in model.lower() else "Cloud Nemotron"
                        if tools_used:
                            engine_badge += " • Tool Assisted"
                        st.caption(f":grey[{engine_badge}]")

                    st.markdown(answer)

                    if citations:
                        st.markdown("##### :material/link: Grounded Sources & Citations")
                        for cite in citations:
                            st.markdown(f"- {cite}")

                    # Voice Output: Synthesize spoken response if enabled
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

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "meta": meta_desc,
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
                    st.error(f"AIRA Engine Error ({status_code}): {err_msg}")


# ==============================================================================
# SECTION 2: MEMORY & PREFERENCES WORKSPACE
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

    # 1. Profile Tab
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
                        # Also persist in memory repository
                        requests.post(f"{BACKEND_URL}/api/memory", json={"key": attr_field, "value": attr_val.strip()})
                        st.success(f"Updated {attr_field.replace('_', ' ').title()}.")
                        st.rerun()

                if user_display_name:
                    if st.button("Reset User Name", width="content"):
                        api_delete("/api/user-profile/name")
                        st.info("User name cleared.")
                        st.rerun()

    # 2. Preferences Tab
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
                                requests.post(f"{BACKEND_URL}/api/preferences/{p['id']}/approve")
                                st.rerun()
                        if st.button("Remove", key=f"del_pref_btn_{p['id']}", width="stretch"):
                            requests.delete(f"{BACKEND_URL}/api/memory/preferences/{p['id']}")
                            st.rerun()
        else:
            st.info("No behavioral preferences recorded yet. They will emerge naturally through conversation.")

    # 3. Episodic Interactions Tab
    with mem_tab3:
        st.markdown("##### Significant Episodic Interactions")
        st.caption("Key conversation summaries, milestone decisions, and learning moments.")

        episodic_records = api_get("/api/memory?category=episodic", [])
        if episodic_records and len(episodic_records) > 0:
            for ep in episodic_records[:12]:
                with st.container(border=True):
                    col_ep1, col_ep2 = st.columns([5, 1])
                    with col_ep1:
                        st.markdown(f"**{ep['title']}** &nbsp;•&nbsp; :grey[{ep['event_type'].title()}]")
                        st.markdown(ep["content"])
                        st.caption(f"Recorded: {ep['created_at'][:19]}")
                    with col_ep2:
                        if st.button("Delete", key=f"del_ep_btn_{ep['id']}", width="stretch"):
                            requests.delete(f"{BACKEND_URL}/api/memory/episodic/{ep['id']}")
                            st.rerun()
        else:
            st.info("No episodic memories stored yet.")

    # 4. Procedural Knowledge Tab
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
                        requests.delete(f"{BACKEND_URL}/api/memory/procedural/{proc['id']}")
                        st.rerun()
        else:
            st.info("No procedural workflows indexed yet.")

    # 5. Export Tab
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
# SECTION 3: PROJECT WORKSPACES
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
                    st.html(f"<div><span style='font-size: 1.25rem; font-weight: 700; color: #F8FAFC;'>{p['name']}</span> &nbsp; <code>{p['id']}</code> &nbsp; {active_badge}</div>")
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
# SECTION 4: KNOWLEDGE BASE / RAG WORKSPACE
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
                            r = requests.post(f"{BACKEND_URL}/api/rag/upload", files=files_payload, data=data_payload, timeout=60.0)
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
                st.warning("🔒 Internet Research is blocked because Local-Only Privacy Mode is active. Switch to Standard in the sidebar to run web research.", icon=":material/lock:")
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
# SECTION 5: SAFEGUARDS WORKSPACE
# ==============================================================================
elif st.session_state.active_section == "Safeguards":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">Operational Safeguards & Identity Constitution</div>
            <div class="aira-workspace-subtitle">Seven core laws enforced at the Python execution layer to ensure safety, alignment, and transparency.</div>
        </div>
    </div>
    """)

    safe_tab1, safe_tab2, safe_tab3 = st.tabs([
        "🛡️ Constitutional Principles",
        "✋ Pending Human Approvals",
        "📜 Security Audit Trail",
    ])

    with safe_tab1:
        constitution_data = api_get("/api/constitution", {})
        principles = constitution_data.get("principles", [])

        col_c1, col_c2 = st.columns([3, 2])
        with col_c1:
            st.markdown("##### The Seven Principles of AIRA")
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

    with safe_tab2:
        st.markdown("##### Operations Requiring Human Confirmation")
        st.caption("High-risk operations (destructive file writes, command execution, test runs) are paused until approved.")

        approvals_list = api_get("/api/approvals", [])
        pending_approvals = [a for a in approvals_list if a.get("status") == "pending"]

        if pending_approvals and len(pending_approvals) > 0:
            for ap in pending_approvals:
                with st.container(border=True):
                    st.warning(f"**Action Paused:** `{ap['tool_name']}` (Risk: `{ap['risk_level'].upper()}`)")
                    st.markdown(f"**Reason:** {ap['reason']}")
                    st.code(json.dumps(ap.get("parameters", {}), indent=2), language="json")

                    col_ap1, col_ap2, _ = st.columns([1, 1, 4])
                    with col_ap1:
                        if st.button("Approve Action", key=f"appr_{ap['id']}", width="stretch"):
                            api_post("/api/approvals/resolve", {"approval_id": ap["id"], "approved": True})
                            st.rerun()
                    with col_ap2:
                        if st.button("Deny Action", key=f"deny_{ap['id']}", width="stretch"):
                            api_post("/api/approvals/resolve", {"approval_id": ap["id"], "approved": False})
                            st.rerun()
        else:
            st.success("All operational boundaries secure. No actions awaiting human approval.")

    with safe_tab3:
        st.markdown("##### Security Audit Trail")
        st.caption("Chronological record of tool decisions, policy checks, and boundary enforcements.")

        audit_logs = api_get("/api/audit-logs", [])
        if audit_logs and len(audit_logs) > 0:
            log_records = []
            for al in audit_logs[:40]:
                log_records.append({
                    "Timestamp": al.get("timestamp", "")[:19],
                    "Action / Tool": al.get("tool_name") or al.get("action", "unknown"),
                    "Risk Level": al.get("risk_level", "low").upper(),
                    "Decision": "ALLOWED" if al.get("allowed", True) else "BLOCKED",
                    "Details": al.get("reason") or str(al.get("parameters", ""))[:50],
                })
            st.dataframe(log_records, width="stretch", hide_index=True)
        else:
            st.info("No audit entries recorded yet.")


# ==============================================================================
# SECTION 6: SYSTEM & DIAGNOSTICS WORKSPACE
# ==============================================================================
elif st.session_state.active_section == "System & Diagnostics":
    st.html("""
    <div class="aira-workspace-header">
        <div>
            <div class="aira-workspace-title">System & Diagnostic Status</div>
            <div class="aira-workspace-subtitle">Live health telemetry, model engine status, response metrics, and benchmark verification.</div>
        </div>
    </div>
    """)

    # Live Status Telemetry Grid
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
            st.markdown("**Memory & Vector DB**")
            st.html('<span class="aira-badge aira-badge-violet">● INITIALIZED</span>')
            st.caption("SQLite + Persistent RAG")

    st.divider()

    # Feedback Analytics
    st.markdown("##### Feedback & Quality Metrics")
    fb_stats = api_get("/api/feedback/metrics", {})

    col_fb1, col_fb2, col_fb3 = st.columns(3)
    col_fb1.metric("Responses Rated", fb_stats.get("total_responses_rated", 0))
    pos_rate = fb_stats.get("positive_rate", 1.0) * 100
    col_fb2.metric("Helpful Rate", f"{pos_rate:.1f}%")
    col_fb3.metric("Issues Reported", fb_stats.get("negative_count", 0))

    st.divider()

    # Verification Benchmark Runner
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