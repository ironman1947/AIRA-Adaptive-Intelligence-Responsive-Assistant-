"""Feedback collection and error analysis for AIRA self-improvement."""

from typing import Dict, Any, Optional, List
from datetime import datetime
from src.memory.models import FeedbackRecord, ProceduralMemory
from src.memory.repository import MemoryRepository

class FeedbackService:
    def __init__(self, repo: MemoryRepository):
        self.repo = repo

    def submit_feedback(
        self,
        request_id: str,
        helpful: bool,
        rating: Optional[int] = None,
        category: str = "helpful",
        user_explanation: Optional[str] = None,
        model_used: Optional[str] = None,
        tools_triggered: bool = False,
        prompt: Optional[str] = None,
        response: Optional[str] = None,
    ) -> FeedbackRecord:
        record = FeedbackRecord(
            request_id=request_id,
            helpful=helpful,
            rating=rating,
            category=category,
            user_explanation=user_explanation,
            model_used=model_used,
            tools_triggered=tools_triggered,
            prompt=prompt,
            response=response,
            created_at=datetime.now().isoformat(),
        )
        saved = self.repo.record_feedback(record)

        # If negative feedback contains a clear correction or error analysis, propose a draft procedural lesson
        if not helpful and user_explanation and category in ("incorrect_fact", "incorrect_code", "user_correction"):
            self._propose_correction_procedure(category, user_explanation, prompt)

        return saved

    def _propose_correction_procedure(self, category: str, explanation: str, prompt: Optional[str]):
        """Proposes a candidate procedural lesson in 'draft' status.

        AIRA requires validation before promoting to 'validated' status.
        """
        title = f"Correction Lesson: {category.replace('_', ' ').title()}"
        applicability = f"Prompts related to: {prompt[:80] if prompt else 'User correction'}"
        steps = [
            f"Note error reported: {explanation}",
            "Verify facts or code syntax against project context and tests",
            "Apply verified correction rather than repeating previous assumption"
        ]
        proc = ProceduralMemory(
            title=title,
            applicability=applicability,
            prerequisites=["Inspect verified project context", "Run regression tests"],
            steps=steps,
            validation_status="draft",  # Starts as draft, requires validation
            success_count=0,
            fail_count=0,
        )
        self.repo.add_procedural(proc)

    def get_feedback_metrics(self) -> Dict[str, Any]:
        all_fb = self.repo.list_feedback(limit=500)
        total = len(all_fb)
        if total == 0:
            return {
                "total_responses_rated": 0,
                "positive_rate": 1.0,
                "negative_count": 0,
                "category_breakdown": {}
            }

        positive = sum(1 for f in all_fb if f.helpful)
        categories = {}
        for f in all_fb:
            categories[f.category] = categories.get(f.category, 0) + 1

        return {
            "total_responses_rated": total,
            "positive_count": positive,
            "negative_count": total - positive,
            "positive_rate": round(positive / total, 3),
            "category_breakdown": categories
        }
