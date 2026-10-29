"""Session Continuity Engine for AIRA.

Creates concise structured session summaries and retrieves relevant context
for subsequent sessions without overloading token context.
"""

from typing import List, Optional
from datetime import datetime
from src.memory.models import SessionSummary
from src.memory.repository import MemoryRepository

class SessionContinuityEngine:
    def __init__(self, repo: MemoryRepository):
        self.repo = repo

    def record_session_summary(
        self,
        session_id: str,
        project_id: Optional[str],
        objective: str,
        accomplished: List[str],
        unfinished: List[str],
        decisions: List[str],
        next_steps: List[str],
    ) -> SessionSummary:
        summary = SessionSummary(
            session_id=session_id,
            project_id=project_id,
            objective=objective,
            accomplished=accomplished,
            unfinished=unfinished,
            decisions_and_corrections=decisions,
            next_steps=next_steps,
            created_at=datetime.now().isoformat(),
        )
        return self.repo.save_session_summary(summary)

    def get_latest_session_prompt_context(self, project_id: Optional[str] = None) -> Optional[str]:
        summary = self.repo.get_latest_session_summary(project_id=project_id)
        if not summary:
            return None

        lines = [
            f"Prior Session Objective: {summary.objective}",
        ]
        if summary.accomplished:
            lines.append("Completed Tasks:")
            for item in summary.accomplished:
                lines.append(f"  - {item}")
        if summary.unfinished:
            lines.append("Unfinished Tasks:")
            for item in summary.unfinished:
                lines.append(f"  - {item}")
        if summary.decisions_and_corrections:
            lines.append("Decisions & User Corrections:")
            for item in summary.decisions_and_corrections:
                lines.append(f"  - {item}")
        if summary.next_steps:
            lines.append("Proposed Next Steps:")
            for item in summary.next_steps:
                lines.append(f"  - {item}")

        return "\n".join(lines)
