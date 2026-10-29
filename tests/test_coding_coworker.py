"""Tests for AIRA Coding Coworker capabilities: workspace inspection, safe editing, diffs, and test runner."""

import json
from pathlib import Path
from src.coding.workspace import get_workspace_tree, read_workspace_file
from src.coding.editor import generate_diff, apply_workspace_edit
from src.coding.tester import run_project_pytest

def test_workspace_tree_and_read(tmp_path):
    sub = tmp_path / "src"
    sub.mkdir()
    f1 = sub / "app.py"
    f1.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")

    tree = get_workspace_tree(str(tmp_path))
    assert "structure" in tree
    assert len(tree["structure"]) == 1
    assert tree["structure"][0]["name"] == "src"

    # Read specific line slice
    res = json.loads(read_workspace_file(str(f1), str(tmp_path), start_line=2, end_line=4))
    assert res["status"] == "success"
    assert "2: line 2" in res["content"]
    assert "4: line 4" in res["content"]
    assert "1: line 1" not in res["content"]

def test_coding_path_traversal_denied(tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("classified")

    res = json.loads(read_workspace_file(str(outside), str(inside)))
    assert res["status"] == "error"
    assert "outside authorized workspace" in res["error"]

def test_generate_diff_and_apply_edit(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("def hello():\n    return 'old'\n")

    diff = generate_diff("def hello():\n    return 'old'\n", "def hello():\n    return 'new'\n", "module.py")
    assert "-    return 'old'" in diff
    assert "+    return 'new'" in diff

    # Dry run preview
    preview = json.loads(apply_workspace_edit(str(target), "def hello():\n    return 'new'\n", str(tmp_path), dry_run=True))
    assert preview["status"] == "preview"
    assert target.read_text() == "def hello():\n    return 'old'\n"

    # Actual apply
    applied = json.loads(apply_workspace_edit(str(target), "def hello():\n    return 'new'\n", str(tmp_path), dry_run=False))
    assert applied["status"] == "applied"
    assert target.read_text() == "def hello():\n    return 'new'\n"

def test_pytest_runner_parsing(tmp_path):
    # Create a small valid test file
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_ok():\n    assert 1 + 1 == 2\n")

    res = json.loads(run_project_pytest(str(tmp_path), test_path=str(test_file)))
    assert res["status"] == "completed"
    assert res["success"] is True
    assert res["counts"]["passed"] >= 1
