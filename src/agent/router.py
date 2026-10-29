"""AIRA Intelligent Dual-Engine Routing Module.

Routes lightweight/private/casual tasks to local Gemma (via Ollama) and complex,
tool-intensive tasks to Cloud Nemotron (via OpenRouter), with privacy enforcement,
intent analysis, and graceful offline fallback.
"""

import os
import re
from typing import Dict, Any, Tuple
from dotenv import load_dotenv
from openai import AsyncOpenAI
import httpx

from src.config import (
    USE_LOCAL_ROUTER,
    LOCAL_BASE_URL,
    LOCAL_MODEL,
    NEBIUS_API_KEY,
    NEBIUS_BASE_URL,
    HEAVY_MODEL,
    CLOUD_LIGHT_MODEL,
    FORCE_LOCAL_ONLY,
)
from src.agent.prompts import COMPLEXITY_ROUTING_PROMPT
from src.agent.intent import analyze_conversational_intent, IntentCategory, ConversationalIntent

load_dotenv()

# Cloud Client (Nemotron via OpenRouter/Nebius)
def get_nebius_client() -> AsyncOpenAI:
    """Returns an AsyncOpenAI client bound to the current running event loop."""
    return AsyncOpenAI(
        base_url=NEBIUS_BASE_URL,
        api_key=NEBIUS_API_KEY or "none",
        timeout=35.0,
    )

def get_light_client() -> AsyncOpenAI:
    """Returns a local Ollama client bound to the current running event loop."""
    if USE_LOCAL_ROUTER:
        return AsyncOpenAI(
            base_url=LOCAL_BASE_URL,
            api_key="ollama",
            timeout=25.0,
        )
    return get_nebius_client()

nebius_client = get_nebius_client()
light_client = get_light_client()
if USE_LOCAL_ROUTER:
    active_light_model = LOCAL_MODEL
else:
    active_light_model = CLOUD_LIGHT_MODEL

async def check_local_health() -> bool:
    """Verifies that the local Ollama instance is reachable."""
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{LOCAL_BASE_URL.replace('/v1', '')}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False

async def check_cloud_health() -> bool:
    """Verifies cloud API connectivity."""
    if not NEBIUS_API_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                f"{NEBIUS_BASE_URL}/models",
                headers={"Authorization": f"Bearer {NEBIUS_API_KEY}"}
            )
            return resp.status_code == 200
    except Exception:
        return False

async def determine_complexity(prompt: str) -> str:
    """Determines task complexity: LOW, MEDIUM, or HEAVY using intent analysis and classification."""
    intent = analyze_conversational_intent(prompt)

    # 1. Greetings, user introductions, casual small-talk, system inquiries, and time queries are LOW
    if intent.category in (IntentCategory.GREETING, IntentCategory.USER_INTRODUCTION, IntentCategory.CASUAL, IntentCategory.SYSTEM_INQUIRY, IntentCategory.TIME_DATE_QUERY):
        return "LOW"

    if intent.category in (IntentCategory.EMOTIONAL_SUPPORT, IntentCategory.CONTINUATION, IntentCategory.GENERAL_KNOWLEDGE, IntentCategory.CREATIVE, IntentCategory.PLANNING):
        return intent.suggested_complexity

    # 2. Explicit web research, desktop actions, or coding technical problems are HEAVY
    if intent.category in (IntentCategory.WEB_RESEARCH, IntentCategory.CODING_TECHNICAL, IntentCategory.DESKTOP_ACTION):
        return "HEAVY"

    # 3. Model-based classification for ambiguous multi-sentence inputs
    few_shot = COMPLEXITY_ROUTING_PROMPT.format(prompt=prompt)

    try:
        response = await light_client.chat.completions.create(
            model=active_light_model,
            messages=[{"role": "user", "content": few_shot}],
            temperature=0.0,
            max_tokens=6,
            timeout=2.5,
        )
        raw_output = response.choices[0].message.content.strip().upper()

        if "HEAVY" in raw_output:
            return "HEAVY"
        if "MEDIUM" in raw_output:
            return "MEDIUM"
        if "LOW" in raw_output:
            return "LOW"
        return "MEDIUM"
    except Exception:
        return intent.suggested_complexity

async def route_request(
    prompt: str,
    privacy_mode: str = "standard",
    force_local: bool = False,
    active_project_id: str = None
) -> Dict[str, Any]:
    """Computes routing target, complexity level, selected model, and intent analysis."""
    intent = analyze_conversational_intent(prompt, active_project_id=active_project_id)
    complexity = intent.suggested_complexity

    # Privacy constraint: If local-only mode is active, strictly keep it local
    if force_local or FORCE_LOCAL_ONLY or privacy_mode == "local_only":
        return {
            "target_engine": "local",
            "model": active_light_model,
            "complexity": complexity,
            "reason": "Local-Only Privacy Policy enforced (Zero external cloud telemetry)",
            "privacy_mode": "local_only",
            "intent": intent,
        }

    # Route based on complexity and intent
    if complexity in ("LOW", "MEDIUM"):
        return {
            "target_engine": "local",
            "model": active_light_model,
            "complexity": complexity,
            "reason": f"Classified as {complexity} ({intent.category.replace('_', ' ').title()}); handled locally",
            "privacy_mode": privacy_mode,
            "intent": intent,
        }
    else:
        return {
            "target_engine": "cloud",
            "model": HEAVY_MODEL,
            "complexity": complexity,
            "reason": f"Classified as HEAVY ({intent.category.replace('_', ' ').title()}); routed to Cloud engine",
            "privacy_mode": privacy_mode,
            "intent": intent,
        }