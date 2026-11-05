"""UI Formatting and Metadata Utilities for AIRA.

Provides pure Python formatting functions independent of the Streamlit runtime,
allowing safe headless evaluation and isolated testing.
"""

from datetime import datetime, date
from typing import Dict, Any, List, Optional


def resolve_engine_and_model_badge(
    msg: Dict[str, Any],
    show_debug_traces: bool = False,
) -> str:
    """Safely extracts engine and model display labels from message metadata.

    Handles missing keys, None values, and legacy formats gracefully without raising AttributeError.
    """
    raw_model = str(msg.get("model") or "").strip()
    raw_engine = str(msg.get("engine") or "").strip().lower()
    model_lower = raw_model.lower()

    if raw_engine == "local" or "gemma" in model_lower:
        engine_label = "Local Gemma 2B"
    elif raw_engine == "cloud" or "nemotron" in model_lower:
        engine_label = "Cloud Nemotron"
    elif raw_engine:
        engine_label = raw_engine.title()
    elif model_lower:
        engine_label = raw_model
    else:
        engine_label = "AIRA Assistant"

    badge_info = engine_label
    if raw_model and show_debug_traces:
        badge_info += f" • `{raw_model}`"
    if msg.get("tools_triggered"):
        badge_info += " • Tool Assisted"

    return badge_info


def group_conversations_by_date(
    conversations: List[Dict[str, Any]],
    today: Optional[date] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Partitions a list of conversations into Today, Yesterday, Previous 7 Days, and Older."""
    now_date = today or datetime.now().date()
    groups: Dict[str, List[Dict[str, Any]]] = {
        "Today": [],
        "Yesterday": [],
        "Previous 7 Days": [],
        "Older": [],
    }

    for conv in conversations:
        up_str = str(conv.get("updated_at") or conv.get("created_at") or "")
        try:
            clean_ts = up_str.replace("Z", "+00:00")
            conv_date = datetime.fromisoformat(clean_ts).date()
            diff_days = (now_date - conv_date).days

            if diff_days == 0:
                groups["Today"].append(conv)
            elif diff_days == 1:
                groups["Yesterday"].append(conv)
            elif 2 <= diff_days <= 7:
                groups["Previous 7 Days"].append(conv)
            else:
                groups["Older"].append(conv)
        except Exception:
            groups["Older"].append(conv)

    return groups
