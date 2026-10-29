"""Tests for AIRA Feedback Service and Benchmark Evaluation Runner."""

import pytest
from src.evaluation.feedback import FeedbackService
from src.evaluation.eval_runner import run_benchmark_evaluation
from src.memory.database import DatabaseManager
from src.memory.repository import MemoryRepository

@pytest.fixture
def feedback_svc(tmp_path):
    db_file = tmp_path / "test_eval.db"
    mgr = DatabaseManager(str(db_file))
    repo = MemoryRepository(mgr)
    return FeedbackService(repo), repo

def test_feedback_submission_and_metrics(feedback_svc):
    svc, repo = feedback_svc

    svc.submit_feedback(
        request_id="req_001",
        helpful=True,
        rating=5,
        category="helpful",
        prompt="Explain recursion",
        response="Recursion is..."
    )

    svc.submit_feedback(
        request_id="req_002",
        helpful=False,
        rating=2,
        category="incorrect_code",
        user_explanation="List index was out of bounds on line 12",
        prompt="Write array slice",
        response="arr[len(arr)]"
    )

    metrics = svc.get_feedback_metrics()
    assert metrics["total_responses_rated"] == 2
    assert metrics["positive_count"] == 1
    assert metrics["negative_count"] == 1
    assert metrics["positive_rate"] == 0.5
    assert "incorrect_code" in metrics["category_breakdown"]

    # Check candidate procedural memory created in 'draft' status
    procedures = repo.get_procedural_memories()
    assert len(procedures) >= 1
    assert procedures[0].validation_status == "draft"

@pytest.mark.asyncio
async def test_benchmark_evaluation_runner():
    report = await run_benchmark_evaluation()
    assert report["benchmark_version"] == "1.0.0"
    assert report["total_cases"] >= 5
    assert report["accuracy_pct"] >= 75.0
    assert len(report["results"]) == report["total_cases"]
