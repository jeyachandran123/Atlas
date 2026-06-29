# Contributing to AI Coding Assistant

## Adding a New Feature

Every feature follows the same pattern:

1. **API router** in `app/api/v1/{feature}/router.py`
2. **Repository methods** in `app/db/repositories.py`
3. **Service logic** inline in the router or in a separate `service.py`
4. **Tests** in `tests/unit/` and `tests/integration/`

## Adding a New Agent (V2+)

1. Create `app/agents/{name}_agent.py` implementing `async def run(state: AgentState) -> AgentState`
2. Add node to `app/agents/orchestrator.py`: `graph.add_node("name", agent.run)`
3. Add conditional edge from the routing node
4. Write tests in `tests/unit/test_{name}_agent.py`

## Adding a New Tool

1. Create `app/agents/tools/{name}_tool.py` extending `BaseTool`
2. Implement `async def _execute(context, **kwargs) -> ToolResult`
3. Register in the agent that uses it
4. Write tests mocking the external system the tool calls

## Adding a New Language to the Indexer

1. Create `app/indexing/languages/{lang}.py` extending `LanguageChunker`
2. Implement `_extract_chunks(content)` using tree-sitter
3. Register in `get_chunker()` factory in `app/indexing/chunker.py`
4. Add tree-sitter language package to `requirements.txt`
5. Write tests with real source files in `tests/unit/test_chunker.py`

## Quality Gates

All must pass before merging:

```bash
ruff check app tests          # lint
black --check app tests       # format
mypy app --ignore-missing-imports  # types
bandit -r app -ll -q          # security
pytest                         # tests (75% coverage required)
```

## Running Locally (without Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # edit with your values
uvicorn app.main:app --reload  # API on http://localhost:8000
python -m app.workers.index_worker  # background worker
```

## Running Tests

```bash
pytest                          # all tests
pytest tests/unit/              # unit tests only
pytest tests/integration/       # integration tests only
pytest -k "test_scanner"        # specific test
pytest --cov=app --cov-report=html  # with HTML coverage report
```
