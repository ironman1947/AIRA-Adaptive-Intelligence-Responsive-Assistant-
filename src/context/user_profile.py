"""User Profile Manager for AIRA.

Maintains user-controlled profile information and preference tracking.
Does NOT fabricate user professions, expertise levels, or preferred languages.
Unknown fields are strictly represented as 'Not configured'.
"""

from typing import Dict, Optional, Any
from src.memory.models import UserProfileItem, UserPreference
from src.memory.repository import MemoryRepository

class UserProfileManager:
    def __init__(self, repo: MemoryRepository):
        self.repo = repo
        self._purge_invented_defaults()

    def _purge_invented_defaults(self):
        """Purges any legacy synthetic defaults previously stored in the database."""
        with self.repo.db.connection() as conn:
            conn.execute("DELETE FROM user_profile WHERE source = 'system_default';")

    def get_profile_dict(self) -> Dict[str, str]:
        """Returns all configured profile attributes."""
        items = self.repo.get_profile()
        return {k: item.value for k, item in items.items()}

    def get_field(self, key: str) -> Optional[str]:
        items = self.repo.get_profile()
        item = items.get(key)
        return item.value if item else None

    def get_user_display_name(self) -> Optional[str]:
        """Returns the user's explicit display name if configured, otherwise None."""
        name = self.get_field("user_display_name") or self.get_field("preferred_name")
        if name and name.lower() not in ("not configured", "unknown", "none", ""):
            return name
        return None

    def set_user_display_name(self, name: str) -> str:
        """Sets the user's explicit display name across both user_display_name and preferred_name."""
        clean = name.strip()
        self.update_profile_field("user_display_name", clean)
        self.update_profile_field("preferred_name", clean)
        return clean

    def clear_user_display_name(self) -> bool:
        """Clears the user's display name."""
        r1 = self.delete_profile_field("user_display_name")
        r2 = self.delete_profile_field("preferred_name")
        return r1 or r2

    def update_profile_field(self, key: str, value: str, is_sensitive: bool = False) -> UserProfileItem:
        clean_val = value.strip()
        item = UserProfileItem(
            key=key,
            value=clean_val,
            source="user_explicit",
            confidence=1.0,
            user_approved=True,
            is_sensitive=is_sensitive,
        )
        return self.repo.set_profile_item(item)

    def delete_profile_field(self, key: str) -> bool:
        return self.repo.delete_profile_item(key)

    def propose_inferred_preference(
        self,
        key: str,
        value: str,
        observation: str,
        confidence: float = 0.65
    ) -> UserPreference:
        """Records an unconfirmed candidate preference inferred from interaction evidence.

        Marked as unapproved until confirmed by the user.
        """
        pref = UserPreference(
            preference_key=key,
            preference_value=value,
            supporting_observations=observation,
            confidence=confidence,
            is_explicit=False,
            user_approved=False,
        )
        return self.repo.add_preference(pref)

    def get_profile_prompt_summary(self, context_category: Optional[str] = None) -> Optional[str]:
        """Assembles approved profile details relevant to the current conversation context.

        Returns None if no profile information or preferences have been configured.
        """
        profile = self.get_profile_dict()
        approved_prefs = self.repo.list_preferences(approved_only=True)

        if not profile and not approved_prefs:
            return None

        lines = []
        for k, v in profile.items():
            if v and v.lower() != "not configured":
                lines.append(f"- {k.replace('_', ' ').title()}: {v}")

        if approved_prefs:
            lines.append("Confirmed Preferences:")
            for p in approved_prefs:
                lines.append(f"  * {p.preference_key}: {p.preference_value}")

        return "\n".join(lines) if lines else None
