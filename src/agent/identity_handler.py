"""AIRA Identity & User Introduction Handler.

Provides conservative extraction of user names and name corrections,
detects direct identity questions, and generates deterministic,
authoritative responses for identity inquiries to guarantee
small local models never confuse assistant and user identities.
"""

import re
from typing import Optional, Dict, Any

RESERVED_OR_INVALID_NAMES = {
    "aira", "assistant", "ai", "bot", "system", "admin", "model",
    "user", "human", "someone", "nobody", "anyone", "everyone",
    "crazy", "back", "later", "tomorrow", "today", "tonight", "soon",
    "here", "there", "maybe", "not", "none", "null", "unknown", "true", "false",
    "please", "sir", "madam", "help", "work", "code", "friend", "dude", "bro",
}

# Patterns for user introductions and corrections
INTRODUCTION_PATTERNS = [
    # "Actually, call me Sam" / "Please call me Sam" / "Call me Sam"
    re.compile(r"^(?:actually,?\s+)?(?:please\s+)?call\s+me\s+([A-Za-z][A-Za-z0-9_-]{0,25})(?:\s+from\s+now\s+on)?[\s!.,?]*$", re.IGNORECASE),
    # "My name is not Om, call me Sam"
    re.compile(r"^my\s+name\s+is\s+not\s+\w+,?\s+(?:call\s+me|it'?s|my\s+name\s+is)\s+([A-Za-z][A-Za-z0-9_-]{0,25})[\s!.,?]*$", re.IGNORECASE),
    # "Actually my name is Sam" / "Actually it's Sam"
    re.compile(r"^actually,?\s+(?:my\s+name\s+is|it'?s)\s+([A-Za-z][A-Za-z0-9_-]{0,25})[\s!.,?]*$", re.IGNORECASE),
    # "Hi my name is Om" / "Hello, I am Om" / "Hey, my name's Om"
    re.compile(r"^(?:h+i+|h+e+l+l+o+|h+e+y+|greetings|good\s+(?:morning|afternoon|evening)),?\s+(?:my\s+name\s+is|my\s+name'?s|i\s+am|i'?m|call\s+me)\s+([A-Za-z][A-Za-z0-9_-]{0,25})[\s!.,?]*$", re.IGNORECASE),
    # "My name is Om" / "I am Om" / "I'm Om"
    re.compile(r"^(?:my\s+name\s+is|my\s+name'?s|i\s+am|i'?m)\s+([A-Za-z][A-Za-z0-9_-]{0,25})[\s!.,?]*$", re.IGNORECASE),
]

# Exclusions to prevent false positives
NEGATIVE_INTRO_PATTERNS = [
    re.compile(r"\b(what\s+is|who\s+is|who\s+are|tell\s+me|do\s+you\s+know|may\s+i\s+know)\b", re.IGNORECASE),
    re.compile(r"\b(friend'?s?|cat'?s?|dog'?s?|pet'?s?|file|project|function|class|variable|repo|database)\s+name\b", re.IGNORECASE),
    re.compile(r"\bcall\s+me\s+(crazy|later|back|if|when|maybe|tomorrow|tonight)\b", re.IGNORECASE),
]

# Patterns for identity questions
ASSISTANT_IDENTITY_PATTERNS = [
    re.compile(r"^(?:may\s+i|can\s+i|could\s+i)\s+know\s+your\s+name[\s!.,?]*$", re.IGNORECASE),
    re.compile(r"^(?:what\s+is|what'?s|tell\s+me)\s+your\s+name[\s!.,?]*$", re.IGNORECASE),
    re.compile(r"^who\s+are\s+you([\s!.,?]+.*)?$", re.IGNORECASE),
    re.compile(r"^(?:what\s+are\s+you\s+called|do\s+you\s+have\s+a\s+name)[\s!.,?]*$", re.IGNORECASE),
    re.compile(r"^(?:please\s+)?introduce\s+yourself[\s!.,?]*$", re.IGNORECASE),
]

USER_IDENTITY_PATTERNS = [
    re.compile(r"^(?:what\s+is|what'?s|tell\s+me)\s+my\s+name[\s!.,?]*$", re.IGNORECASE),
    re.compile(r"^(?:do\s+you\s+know|do\s+you\s+remember|can\s+you\s+recall)\s+my\s+name[\s!.,?]*$", re.IGNORECASE),
    re.compile(r"^who\s+am\s+i[\s!.,?]*$", re.IGNORECASE),
]


def extract_user_introduction(prompt: str) -> Optional[Dict[str, Any]]:
    """Conservatively extracts an explicit user name introduction or correction from user prompt.

    Returns dict with keys: 'name', 'is_correction', 'has_greeting', or None if no valid introduction.
    """
    text = prompt.strip()

    # Check negative exclusions first
    for neg in NEGATIVE_INTRO_PATTERNS:
        if neg.search(text):
            return None

    # Check for corrections: "actually", "not X, call me Y"
    is_correction = bool(re.search(r"\b(actually|not\s+\w+,?\s+call\s+me|from\s+now\s+on)\b", text, re.IGNORECASE))
    has_greeting = bool(re.search(r"^(?:h+i+|h+e+l+l+o+|h+e+y+|greetings|good\s+(?:morning|afternoon|evening))\b", text, re.IGNORECASE))

    for pat in INTRODUCTION_PATTERNS:
        m = pat.match(text)
        if m:
            raw_name = m.group(1).strip()
            # Clean any trailing punctuation
            clean_name = re.sub(r"[^\w-]", "", raw_name)
            if not clean_name:
                continue

            lower_name = clean_name.lower()
            if lower_name in RESERVED_OR_INVALID_NAMES:
                return None

            # Format name: capitalize first letter of name
            formatted_name = clean_name.capitalize() if clean_name.islower() else clean_name
            return {
                "name": formatted_name,
                "is_correction": is_correction,
                "has_greeting": has_greeting,
            }

    return None


def detect_identity_question(prompt: str) -> Optional[str]:
    """Detects whether prompt is a direct identity question.

    Returns:
    - 'ask_assistant_name': user asking for AIRA's identity/name
    - 'ask_user_name': user asking for their own name
    - None: neither
    """
    text = prompt.strip()

    for pat in ASSISTANT_IDENTITY_PATTERNS:
        if pat.match(text):
            return "ask_assistant_name"

    for pat in USER_IDENTITY_PATTERNS:
        if pat.match(text):
            return "ask_user_name"

    return None


def generate_assistant_name_response(user_display_name: Optional[str] = None) -> str:
    """Deterministic, natural response identifying AIRA as the assistant."""
    if user_display_name and user_display_name.lower() not in ("not configured", "unknown", "none"):
        return f"I'm AIRA, your personal AI assistant. How can I help you today, {user_display_name}?"
    return "I'm AIRA, your personal AI assistant. How can I help you today?"


def generate_user_name_response(user_display_name: Optional[str] = None) -> str:
    """Deterministic, accurate response for user's identity."""
    if user_display_name and user_display_name.lower() not in ("not configured", "unknown", "none"):
        return f"You told me your name is {user_display_name}."
    return "You haven't told me your name yet. What should I call you?"


def generate_introduction_response(name: str, is_correction: bool = False, has_greeting: bool = False) -> str:
    """Deterministic, warm response greeting or acknowledging user's name."""
    if is_correction:
        return f"Got it! I'll call you {name} from now on. How can I help you today?"
    return f"Hello {name}! It's a pleasure to meet you. How can I help you today?"
