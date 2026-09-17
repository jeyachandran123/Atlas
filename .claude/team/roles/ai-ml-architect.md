# ai-ml-architect — UnityWorks AI Assistant backend brief

**REQUIRED:** read `.claude/skills/unityworks-ai-ml/SKILL.md` first. It is this project's map for the
plugin's `ai-ml-architecture` method: the serving-path order of `POST /api/v1/chat/stream`, every other
model entry point and its provider switch, the `app/llm/` profile layer, where each prompt lives,
retrieval and embedding traps, the grounding invariants, config traps and verification commands.

## Project specifics for the procedure
- Configuration values come from `app/config.py` (and the environment the user names — never `.env`).
- With default config `COGNITIVE_BRAIN_ENABLED` is on, so ordinary streaming chat uses `_STREAM_SYSTEM`
  in `app/cognitive_integration/pipeline.py`, not `app/prompts/modules/`.
- Tests: `.\venv\Scripts\python.exe -m pytest <tests> --no-cov` (the 75% coverage gate is in `addopts`);
  the fake `AsyncOpenAI` pattern is in `tests/unit/test_llm_gateway.py`.
- Real-path runs: `scripts/e2e_dip_*.py`, `scripts/e2e_chat_docs.py` — only with authorisation.

## What breaks here
- Grounding: `DIP_GROUNDING_MIN_SCORE` lowered, uncited text accepted, validator rejections caught, or a
  low grounding score treated as recoverable (`gateway._recoverable`).
- Provider names inside `app/document_platform/vlm/` or the extraction API; adapters composing prompts.
- Document tasks' generated code reaching the network (`execution/sandbox.py` runs `--network none`).
- Cognitive OS boundaries: kernel importing beyond stdlib, engines importing each other, high-stakes
  turns auto-answered.
- Config traps to confirm against current code: `CHROMA_PORT` defaults to 8000, `DIP_LLM_PROVIDER` is
  read by nothing, `dip_chat_model` does not exist, `NVIDIA_TEMPERATURE` / `NVIDIA_MAX_TOKENS` are not
  read by the gateway, `VISION_PROVIDER` defaults to `nvidia`.
- `docker compose down` is blocked for everyone here (it destroyed the database once).
