"""Prompt templates and builders for AIRA workflows."""

COMPLEXITY_ROUTING_PROMPT = """You are AIRA's internal task classification engine.
Analyze the user request and classify its computational and capability complexity into exactly one token: LOW, MEDIUM, or HEAVY.

Guidelines:
- LOW: Simple greetings, general chit-chat, trivial questions, simple jokes, basic definitions.
- MEDIUM: Text rewriting, simple summarization, straightforward explanations, basic formatting.
- HEAVY: Complex coding tasks, deep debugging, architecture design, multi-step problem solving, math logic, research questions requiring up-to-date real-time tools, deep reasoning.

Task: "Hello, how are you today?"
Classification: LOW

Task: "Explain what an API is in simple words."
Classification: MEDIUM

Task: "Write a high-performance LRU cache in Python with thread-safe locks."
Classification: HEAVY

Task: "Debug this async race condition and explain why it deadlocks."
Classification: HEAVY

Task: "{prompt}"
Classification:"""

SESSION_SUMMARY_PROMPT = """Analyze the following conversation session between the user and AIRA.
Produce a concise, structured JSON summary for session continuity:
{{
  "objective": "What the user was attempting to achieve",
  "accomplished": ["List of completed tasks/milestones"],
  "unfinished": ["List of remaining or ongoing tasks"],
  "decisions_and_corrections": ["Key architectural decisions or user corrections"],
  "next_steps": ["Recommended immediate next actions"]
}}

Conversation:
{conversation_text}

JSON:"""

ERROR_ANALYSIS_PROMPT = """You are analyzing user feedback on an AIRA response.
User Feedback Category: {category}
User Explanation: {user_explanation}
Original User Prompt: {prompt}
AIRA Response: {response}

Analyze the failure:
1. What was the root error (factual claim, flawed logic, tool execution failure, code bug, style mismatch)?
2. What is the verified correction?
3. What reusable lesson or procedural rule can be proposed to avoid this mistake in the future?
"""
