# qa-engineer — UnityWorks AI Assistant backend brief

## What to know
- `pyproject.toml` `addopts` carries `--cov=app --cov-fail-under=75`: every subset run needs `--no-cov`.
- Run with `.\venv\Scripts\python.exe -m pytest …` (venv is Python 3.11.9).
- No test may reach a model provider — follow the fake `AsyncOpenAI` pattern in
  `tests/unit/test_llm_gateway.py`.
- Known local failures (2026-09-17), listed in the `unityworks-ai-ml` skill: three tree-sitter chunker
  tests (grammars not installed), `document_vlm` default/host tests that read the local `.env` (tests not
  isolated from `.env` — a real test-hygiene finding), and two confidence-evaluator tests (real
  mismatch: `MEDIUM` vs `VERY_LOW`).
- Intelligence engine "short-circuits before any LLM call" has no dedicated test.
