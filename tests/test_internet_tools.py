"""Tests for AIRA Internet Tools, Safe Fetching, and Logic Evaluation."""

import json
from unittest.mock import patch, MagicMock
from src.tools.internet import search_web, fetch_webpage, SEARCH_WEB_SCHEMA, FETCH_WEBPAGE_SCHEMA
from src.tools.logic_eval import evaluate_logic, EVALUATE_LOGIC_SCHEMA

def test_search_web_empty_query():
    res = json.loads(search_web(""))
    assert "error" in res

def test_search_web_mocked():
    with patch("src.tools.internet.DDGS") as mock_ddgs:
        instance = mock_ddgs.return_value.__enter__.return_value
        instance.text.return_value = [
            {"title": "Python Docs", "body": "Official documentation", "href": "https://python.org"}
        ]
        output = search_web("python docs")
        data = json.loads(output)
        assert data["status"] == "success"
        assert len(data["results"]) == 1
        assert data["results"][0]["url"] == "https://python.org"

def test_fetch_webpage_ssrf_blocked():
    output = fetch_webpage("http://127.0.0.1:8080/secret")
    data = json.loads(output)
    assert data["status"] == "blocked_by_security_policy"
    assert "prohibited" in data["error"].lower() or "blocked" in data["error"].lower()

def test_fetch_webpage_mocked_success():
    with patch("src.tools.internet.validate_url_security", return_value=(True, "")):
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.headers = {"Content-Length": "100"}
            mock_resp.encoding = "utf-8"
            mock_resp.iter_content.return_value = [b"<html><head><title>Test Page</title></head><body><h1>Hello World</h1><p>Test content.</p></body></html>"]
            mock_resp.__enter__.return_value = mock_resp
            mock_get.return_value = mock_resp

            output = fetch_webpage("https://example.com/test")
            data = json.loads(output)
            assert data["status"] == "success"
            assert data["title"] == "Test Page"
            assert "Hello World" in data["content"]

def test_safe_logic_eval():
    res1 = json.loads(evaluate_logic("(10 * 5) + 2"))
    assert res1["status"] == "success"
    assert res1["result"] == 52

    res2 = json.loads(evaluate_logic("100 > 50 and 20 <= 25"))
    assert res2["status"] == "success"
    assert res2["result"] is True

    # Block unsafe function calls or code injection
    res3 = json.loads(evaluate_logic("__import__('os').system('ls')"))
    assert res3["status"] == "error"
