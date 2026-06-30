"""
Review prompts for the ReviewAgent.

The ReviewAgent is adversarial — it looks for problems, not just validation.
Separate from coding.py to maintain clear separation of concerns.

Design principles:
- Be adversarial but constructive
- Focus on real issues, not style nitpicks
- Provide concrete, actionable feedback
- Consider the codebase context
"""

from __future__ import annotations

REVIEW_SYSTEM_PROMPT = """You are a senior software engineer conducting a critical code review.
Your role is ADVERSARIAL — actively look for problems in the code changes.

Review criteria (in priority order):
1. **Correctness**: Does the code actually solve the user's request? Are there bugs or logic errors?
2. **Security**: Are there SQL injection, XSS, path traversal, or other security vulnerabilities?
3. **Performance**: Are there obvious performance issues (N+1 queries, unnecessary loops)?
4. **Maintainability**: Does the code follow existing patterns? Is it overly complex?
5. **Completeness**: Are edge cases handled? Is error handling sufficient?

What NOT to review:
- Don't nitpick style unless it creates real maintainability issues
- Don't suggest improvements that weren't requested
- Don't block on minor issues that don't affect functionality

Your response format:
If the code is acceptable (no critical issues):
  APPROVED

If there are problems that must be fixed:
  NEEDS_REVISION
  
  Issue 1: [Specific problem]
  Why: [Why this is a problem]
  Fix: [Concrete suggestion]
  
  Issue 2: ...

Be direct. Be specific. Be constructive."""


def build_review_prompt(
    draft_output: str,
    user_request: str,
    files_modified: list[str],
    code_context: str,
    tool_results: list[str],
) -> str:
    """
    Build the review prompt for the ReviewAgent.

    Structure:
      [USER REQUEST] What the user asked for
      [AGENT RESPONSE] The code/changes the agent produced
      [FILES MODIFIED] Which files were changed
      [TOOL RESULTS] What the agent actually did
      [CONTEXT] Relevant code from the codebase
      [TASK] Review the response
    """
    parts: list[str] = []

    # 1. User request (what was asked for)
    parts.append(f"<user_request>\n{user_request}\n</user_request>")

    # 2. Agent's draft response
    parts.append(f"<agent_response>\n{draft_output}\n</agent_response>")

    # 3. Files modified (if any)
    if files_modified:
        files_list = "\n".join(f"- {f}" for f in files_modified)
        parts.append(f"<files_modified>\n{files_list}\n</files_modified>")

    # 4. Tool results (what actually happened)
    if tool_results:
        tool_output = "\n\n".join(tool_results)
        parts.append(f"<tool_execution>\n{tool_output}\n</tool_execution>")

    # 5. Codebase context
    if code_context and code_context != "No relevant code context found.":
        parts.append(f"<codebase_context>\n{code_context}\n</codebase_context>")

    # 6. Review task
    parts.append(
        "<task>\n"
        "Review the agent's response against the user's request.\n"
        "Check for correctness, security issues, bugs, and completeness.\n"
        "Respond with either 'APPROVED' or 'NEEDS_REVISION' followed by specific issues.\n"
        "</task>"
    )

    return "\n\n".join(parts)


def parse_review_response(response: str) -> tuple[str, str]:
    """
    Parse the LLM's review response into status and feedback.

    Returns:
        (status, feedback) where status is "approved" or "needs_revision"
    """
    response = response.strip()
    
    # Check if response starts with APPROVED or NEEDS_REVISION
    if response.upper().startswith("APPROVED"):
        return ("approved", "")
    
    if response.upper().startswith("NEEDS_REVISION") or response.upper().startswith("NEEDS REVISION"):
        # Extract everything after NEEDS_REVISION as feedback
        lines = response.split("\n", 1)
        feedback = lines[1].strip() if len(lines) > 1 else response
        return ("needs_revision", feedback)
    
    # Default: if response contains critical words, treat as needs_revision
    critical_words = ["bug", "error", "issue", "problem", "security", "vulnerability", "incorrect"]
    if any(word in response.lower() for word in critical_words):
        return ("needs_revision", response)
    
    # Otherwise approve
    return ("approved", "")
