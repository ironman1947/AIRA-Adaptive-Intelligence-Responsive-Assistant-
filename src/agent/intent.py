"""AIRA Conversational Intelligence & Intent Understanding Subsystem.

Analyzes the user's conversational intent, emotional tone, and contextual needs
before deciding how to route, what context to retrieve, and what response style fits.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from src.agent.identity_handler import detect_identity_question, extract_user_introduction

class IntentCategory:
    GREETING = "greeting"
    CASUAL = "casual"
    CONTINUATION = "continuation"
    GENERAL_KNOWLEDGE = "general_knowledge"
    LEARNING_EDUCATION = "learning_education"
    EMOTIONAL_SUPPORT = "emotional_support"
    CREATIVE = "creative"
    PLANNING = "planning"
    CODING_TECHNICAL = "coding_technical"
    WEB_RESEARCH = "web_research"
    RAG_DOCUMENT = "rag_document"
    SYSTEM_INQUIRY = "system_inquiry"
    USER_INTRODUCTION = "user_introduction"
    TIME_DATE_QUERY = "time_date_query"
    DESKTOP_ACTION = "desktop_action"
    OTHER = "other"

@dataclass
class ConversationalIntent:
    category: str
    emotional_cue: Optional[str] = None  # frustrated, excited, exhausted, confused, reflective, neutral
    needs_project_context: bool = False
    needs_web_search: bool = False
    needs_coding_tools: bool = False
    needs_rag: bool = False
    needs_clarification: bool = False
    tone_guidance: Optional[str] = None
    suggested_complexity: str = "LOW"  # LOW, MEDIUM, HEAVY
    identity_query_type: Optional[str] = None  # ask_assistant_name | ask_user_name
    extracted_user_name: Optional[str] = None
    is_name_correction: bool = False

GREETING_PATTERNS = [
    re.compile(r"^(h+i+|h+e+l+l+o+|h+e+y+|h+a+l+l+o+|h+o+l+a+|s+u+p+|y+o+|greetings|howdy)([\s!.,?]+.*)?$", re.IGNORECASE),
    re.compile(r"^(good\s+(morning|afternoon|evening|day)|what'?s\s+up|how\s+are\s+you(\s+doing)?(\s+today)?|how\'?s\s+it\s+going)[\s!.,?]*$", re.IGNORECASE),
]

CONTINUATION_PATTERNS = [
    re.compile(r"\b(let'?s\s+continue|continue\s+from|pick\s+up\s+where|where\s+were\s+we|what\s+was\s+i\s+doing|resume|next\s+step)\b", re.IGNORECASE),
    re.compile(r"\b(tell\s+me\s+more(\s+about)?(\s+that)?|elaborate(\s+on)?|explain\s+that(\s+with\s+an\s+example|\s+further)?|can\s+you\s+explain\s+that)\b", re.IGNORECASE),
    re.compile(r"\b(make\s+(it|that)\s+(shorter|longer|simpler|more\s+concise|brief|detailed|quicker))\b", re.IGNORECASE),
    re.compile(r"\b(explain\s+(it|that|this)\s+(more\s+simply|simply|in\s+simpler\s+terms))\b", re.IGNORECASE),
    re.compile(r"\b(the\s+(second|first|third|last|previous|next)\s+(story|one|point|item|article|news|topic))\b", re.IGNORECASE),
    re.compile(r"\b(what\s+about\s+(that|the\s+other|the\s+second|it)|how\s+about\s+(that|it))\b", re.IGNORECASE),
    re.compile(r"\b((give|provide)\s+me\s+(another|an)\s+example|explain\s+(the\s+first|the\s+second|that)\s+one(\s+again)?|what\s+did\s+you\s+mean\s+by\s+that)\b", re.IGNORECASE),
    re.compile(r"\b(what\s+should\s+i\s+(learn|do|start\s+with|read)\s+(first|next|after\s+this|after\s+that))\b", re.IGNORECASE),
    re.compile(r"\b(no,?\s+something\s+(simpler|different|more\s+practical|easier))\b", re.IGNORECASE),
]

SHORT_ACKNOWLEDGMENT_PATTERNS = [
    re.compile(r"^\s*(yeah|yes|yep|sure|ok|okay|no|nope|nah|not\s+really|you\s+too|sounds\s+good|got\s+it|understood|alright|thanks|thank\s+you)[\s!.,?]*$", re.IGNORECASE),
]

AMBIGUOUS_KEYWORD_PATTERNS = [
    re.compile(r"^\s*(youtube|spotify|netflix|google|safari|chrome|slack|discord|reddit|twitter|github)[\s!.,?]*$", re.IGNORECASE),
]

FRUSTRATION_PATTERNS = [
    re.compile(r"\b(keeps?\s+failing|tried\s+everything|doesn'?t\s+work|nothing\s+works|so\s+frustrated|hate\s+this|driving\s+me\s+crazy|stuck\s+on\s+this|fed\s+up|failing\s+again)\b", re.IGNORECASE),
]

EXCITEMENT_PATTERNS = [
    re.compile(r"\b(it\s+finally\s+worked|finally\s+working|we\s+did\s+it|it\s+works!?|yes!+|awesome!+|hooray|hurray)\b", re.IGNORECASE),
    re.compile(r"^[A-Z\s!]{4,}!+$"),  # ALL CAPS excitement with exclamation marks e.g. "IT FINALLY WORKED!"
]

SYSTEM_INQUIRY_PATTERNS = [
    re.compile(r"\b(who\s+are\s+you|what\s+is\s+your\s+name|what\s+can\s+you\s+do|your\s+capabilities|system\s+status|about\s+aira|what\s+model)\b", re.IGNORECASE),
]

TIME_DATE_PATTERNS = [
    # Explicit time queries
    re.compile(r"^(what'?s|what\s+is)\s+(the\s+)?(current\s+|local\s+|system\s+)?time[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"^what\s+time(\s+is\s+it)?[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"^(tell\s+me\s+)?(the\s+)?(current\s+|system\s+|local\s+)?time(\s+now|\s+please)?[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"^(time\s+now|current\s+time|current\s+system\s+time|the\s+time|time\s+please|system\s+time|local\s+time)[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"\b(what\s+is\s+the\s+system\s+time|current\s+system\s+time|tell\s+me\s+the\s+system\s+time)\b", re.IGNORECASE),
    # Explicit date queries
    re.compile(r"^(what'?s|what\s+is)\s+(the\s+)?(current\s+|today'?s\s+)?date[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"^(what\s+day\s+is\s+it|what\s+day\s+is\s+today|what\s+is\s+today|today'?s\s+date|the\s+date|current\s+date|date\s+today)[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"^(tell\s+me\s+)?(the\s+)?(current\s+)?date(\s+today|\s+now)?[\s!?,.]*$", re.IGNORECASE),
    # Combined time and date queries
    re.compile(r"^(what'?s|what\s+is)\s+(the\s+)?(current\s+)?(time\s+and\s+date|date\s+and\s+time)[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"^(time\s+and\s+date|date\s+and\s+time)[\s!?,.]*$", re.IGNORECASE),
]

DESKTOP_ACTION_PATTERNS = [
    re.compile(r"^\s*(open|launch|start|run|quit|close)\s+([a-zA-Z0-9_\-\s]+?)[\s!?,.]*$", re.IGNORECASE),
    re.compile(r"\b(open\s+(safari|chrome|terminal|notes|finder|calculator|settings|calendar|slack|vscode|code)|launch\s+(safari|chrome|terminal|notes|finder|calculator|settings|calendar|slack|vscode|code))\b", re.IGNORECASE),
    re.compile(r"\b(open\s+https?://\S+|open\s+url\s+\S+)\b", re.IGNORECASE),
    re.compile(r"\b(search\s+youtube\s+for\s+.+|play\s+.+\s+on\s+youtube|look\s+up\s+.+\s+on\s+youtube)\b", re.IGNORECASE),
    re.compile(r"\b(system\s+diagnostics|mac\s+diagnostics|show\s+running\s+apps|list\s+running\s+apps|running\s+applications)\b", re.IGNORECASE),
]

WEB_RESEARCH_PATTERNS = [
    # Explicit research action commands
    re.compile(r"\b(research(\s+a\s+topic(\s+for\s+me)?)?|do\s+some\s+research(\s+on|\s+into)?|conduct\s+research(\s+on|\s+into)?)\b", re.IGNORECASE),
    re.compile(r"\b(find(\s+the)?\s+(latest|current|recent)\s+(information|developments|updates|news|sources))\b", re.IGNORECASE),
    re.compile(r"\b(investigate(\s+the|\s+current|\s+latest)?\s+(best\s+practices|recent|developments|trends|architecture))\b", re.IGNORECASE),
    re.compile(r"\b(compare(\s+the)?\s+recent\s+(developments|trends|approaches|practices))\b", re.IGNORECASE),
    re.compile(r"\b(gather\s+(evidence|sources|references|data\s+on))\b", re.IGNORECASE),
    re.compile(r"\b(summarize(\s+the)?\s+current\s+(technical\s+guidance|best\s+practices|state\s+of))\b", re.IGNORECASE),
    # Web search triggers
    re.compile(r"\b(search\s+(the\s+web|online|internet|for)|look\s+up\s+(online|on\s+the\s+web))\b", re.IGNORECASE),
    re.compile(r"\b(latest\s+(news|best\s+practices|developments|guidelines|standards)|current\s+news|today'?s\s+news|stock\s+price|current\s+weather|breaking\s+news)\b", re.IGNORECASE),
    re.compile(r"\b(who\s+won\s+the\s+202[4-9]|current\s+events|happened\s+recently|in\s+the\s+news)\b", re.IGNORECASE),
]

CODING_TECHNICAL_PATTERNS = [
    re.compile(r"\b(def\s+\w+|function\s+\w+|class\s+\w+|import\s+\w+|async\s+def|git\s+|pytest|docker|sql|endpoint|fastapi|streamlit|traceback|syntaxerror|nullpointer|bug|stack\s*trace)\b", re.IGNORECASE),
    re.compile(r"\b(write\s+(a\s+)?([a-zA-Z0-9_-]+\s+)?(script|code|program|algorithm|class|function|test|tree|solution)|refactor|debug\s+this|fix\s+this\s+code)\b", re.IGNORECASE),
]

GENERAL_KNOWLEDGE_PATTERNS = [
    re.compile(r"^(why\s+do\s+|how\s+do\s+|what\s+is\s+(the\s+|a\s+|an\s+)?(history|meaning|cause|distance|speed|capital|origin|system|definition|concept|theory|principle)\s+of|who\s+(was|wrote|discovered|invented|painted)|explain\s+|tell\s+me\s+about\s+|how\s+does\s+.*\s+work)\b", re.IGNORECASE),
    re.compile(r"^(what\s+is\s+(a\s+|an\s+|the\s+)?(system\s+of\s+time|relativity|quantum|gravity|entropy|photosynthesis|calculus|evolution|dna|rna|machine\s+learning|deep\s+learning|artificial\s+intelligence|rag|ai))\b", re.IGNORECASE),
]

def analyze_conversational_intent(prompt: str, active_project_id: Optional[str] = None) -> ConversationalIntent:
    """Classifies the primary conversational purpose, tone cues, and required context."""
    text = prompt.strip()
    clean_lower = text.lower()

    # 0. Check for Direct Identity Inquiries (Assistant or User name)
    identity_query = detect_identity_question(text)
    if identity_query == "ask_assistant_name":
        return ConversationalIntent(
            category=IntentCategory.SYSTEM_INQUIRY,
            identity_query_type="ask_assistant_name",
            suggested_complexity="LOW",
            needs_project_context=False,
            tone_guidance="Directly identify yourself as AIRA, your personal AI assistant."
        )
    elif identity_query == "ask_user_name":
        return ConversationalIntent(
            category=IntentCategory.SYSTEM_INQUIRY,
            identity_query_type="ask_user_name",
            suggested_complexity="LOW",
            needs_project_context=False,
            tone_guidance="State the user's name if they have introduced themselves, or say you don't know yet and ask."
        )

    # 1. Check for Explicit User Introductions & Name Corrections (e.g. 'hi my name is om', 'call me Sam')
    user_intro = extract_user_introduction(text)
    if user_intro:
        return ConversationalIntent(
            category=IntentCategory.USER_INTRODUCTION,
            extracted_user_name=user_intro["name"],
            is_name_correction=user_intro["is_correction"],
            suggested_complexity="LOW",
            needs_project_context=False,
            tone_guidance="Acknowledge the user's name warmly, with natural conversational brevity."
        )

    # 2. Check for System Time or Date Query (Fast path)
    for pat in TIME_DATE_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.TIME_DATE_QUERY,
                suggested_complexity="LOW",
                needs_project_context=False,
                tone_guidance="State the exact current system time and date clearly and concisely."
            )

    # 3. Check for Desktop Action / Application Control
    for pat in DESKTOP_ACTION_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.DESKTOP_ACTION,
                suggested_complexity="HEAVY",
                needs_coding_tools=True,
                tone_guidance="Propose and execute authorized desktop operations subject to policy confirmation."
            )

    # 4. Check for Web Research (Priority over Greetings and Casual)
    for pat in WEB_RESEARCH_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.WEB_RESEARCH,
                suggested_complexity="HEAVY",
                needs_web_search=True,
                tone_guidance="Perform a verified web search and synthesize the findings with clear source citations."
            )

    # 5. Check for Greeting (Fast path)
    for pat in GREETING_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.GREETING,
                suggested_complexity="LOW",
                needs_project_context=False,
                tone_guidance="Respond naturally, warmly, and concisely with a friendly greeting. Do not recite project status, technical objectives, or system statistics."
            )

    # 2. Check for Emotional Cues
    # Frustration
    for pat in FRUSTRATION_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.EMOTIONAL_SUPPORT,
                emotional_cue="frustrated",
                suggested_complexity="MEDIUM",
                needs_project_context=True if active_project_id else False,
                needs_coding_tools=bool(re.search(r"\b(code|build|test|script|error|bug)\b", clean_lower)),
                tone_guidance="Acknowledge the frustration with calm, attentive empathy without overreacting or assuming to know their thoughts (e.g. 'That sounds frustrating. Let's take a breath and isolate what's failing.'). Offer to investigate methodically."
            )

    # Excitement
    for pat in EXCITEMENT_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.EMOTIONAL_SUPPORT,
                emotional_cue="excited",
                suggested_complexity="LOW",
                needs_project_context=False,
                tone_guidance="Match the user's enthusiasm with warm celebration (e.g. 'That is awesome! Getting it to work after all that effort feels fantastic.'). Offer an optional, relevant next step if they want to continue."
            )

    # 2.5 Check for Short Acknowledgments / Conversational Follow-up Replies (e.g. "Yeah.", "You too.")
    for pat in SHORT_ACKNOWLEDGMENT_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.CASUAL,
                suggested_complexity="LOW",
                needs_project_context=False,
                tone_guidance="The user provided a short acknowledgement or natural conversational reply. Interpret this in the direct context of the immediately preceding assistant turn. Do not introduce yourself or generate generic greetings."
            )

    # 2.6 Check for Ambiguous Single-Keyword App/Brand Utterances (e.g. "YouTube.")
    for pat in AMBIGUOUS_KEYWORD_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.CASUAL,
                suggested_complexity="LOW",
                needs_project_context=False,
                tone_guidance=f"The user said only the isolated keyword '{text}'. Politely clarify whether they would like you to open the application or discuss topics related to it, without inventing unrequested actions."
            )

    # 3. Check for Continuation & Contextual Follow-ups
    for pat in CONTINUATION_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.CONTINUATION,
                suggested_complexity="MEDIUM",
                needs_project_context=True,
                tone_guidance="Retrieve recent conversation context and continue seamlessly. Resolve pronouns and references (e.g., 'that', 'the second story', 'make it shorter') using the immediately preceding assistant message."
            )

    # 5. Check for Coding / Technical
    for pat in CODING_TECHNICAL_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.CODING_TECHNICAL,
                suggested_complexity="HEAVY",
                needs_project_context=True,
                needs_coding_tools=True,
                tone_guidance="Provide precise, methodical, and well-structured technical reasoning or code."
            )

    # 6. Check for System Inquiry
    for pat in SYSTEM_INQUIRY_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.SYSTEM_INQUIRY,
                suggested_complexity="LOW",
                needs_project_context=False,
                tone_guidance="Introduce your capabilities as AIRA: a general-purpose, persistent personal assistant and coworker supporting conversation, research, learning, planning, and technical work."
            )

    # 7. Check for General Knowledge / Conceptual Explanations
    for pat in GENERAL_KNOWLEDGE_PATTERNS:
        if pat.search(text):
            return ConversationalIntent(
                category=IntentCategory.GENERAL_KNOWLEDGE,
                suggested_complexity="HEAVY",
                needs_project_context=False,
                tone_guidance="Directly explain the concept requested without any greetings, pleasantries, or self-introductions. Begin the factual explanation immediately."
            )

    # 8. Check for Creative or Planning
    if re.search(r"\b(write\s+a\s+(story|poem|essay|song)|brainstorm|creative|name\s+for|imagine)\b", clean_lower):
        return ConversationalIntent(
            category=IntentCategory.CREATIVE,
            suggested_complexity="MEDIUM",
            needs_project_context=False,
            tone_guidance="Be imaginative, expressive, and thoughtful while distinguishing creative invention from factual reality."
        )

    if re.search(r"\b(plan|schedule|routine|habit|to-?do|organize\s+my|productivity|prioritize)\b", clean_lower):
        return ConversationalIntent(
            category=IntentCategory.PLANNING,
            suggested_complexity="MEDIUM",
            needs_project_context=False,
            tone_guidance="Help structure goals and priorities into practical, balanced, and actionable steps."
        )

    # Default: Casual conversation or general task
    return ConversationalIntent(
        category=IntentCategory.CASUAL,
        suggested_complexity="LOW" if len(text) < 150 else "MEDIUM",
        needs_project_context=False,
        tone_guidance="Respond conversationally, attentively, and helpfully."
    )
