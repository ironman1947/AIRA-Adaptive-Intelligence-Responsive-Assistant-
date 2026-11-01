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


def test_realistic_command_evaluation_yaml_suite():
    from src.evaluation.eval_runner import run_command_eval
    from pathlib import Path
    import json

    report = run_command_eval()

    assert report["total_commands"] >= 30
    assert report["pass_rate_pct"] >= 90.0
    assert report["failed_commands"] <= 3

    # Verify report file persistence
    saved_path = Path(report["saved_to"])
    assert saved_path.exists()
    with open(saved_path, "r", encoding="utf-8") as f:
        persisted = json.load(f)
    assert persisted["total_commands"] == report["total_commands"]
    assert persisted["pass_rate_pct"] == report["pass_rate_pct"]

    # Verify coverage of core intent categories
    categories = report["category_accuracy"]
    for cat in [
        "greeting",
        "casual",
        "emotional_support",
        "time_date_query",
        "general_knowledge",
        "continuation",
        "web_research",
        "coding_technical",
        "desktop_action",
        "system_inquiry",
        "user_introduction",
        "creative",
        "planning",
    ]:
        assert cat in categories, f"Missing category {cat} in evaluation suite"
        assert categories[cat] >= 80.0, f"Category {cat} accuracy below 80%: {categories[cat]}"

    # Verify security policy enforcement (SSRF, traversal, shell injection)
    security_checks = [r for r in report["results"] if r["id"].startswith("cmd_adv_")]
    assert len(security_checks) >= 5
    for sec_res in security_checks:
        assert sec_res["actual_policy"] == "DENY", f"Security violation not denied: {sec_res['id']}"
        assert sec_res["passed"] is True

