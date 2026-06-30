# Quick Start — Testing P0/P1 Fixes

## What Changed

✅ **P0 Blockers Resolved** (see `docs/development/P0_BLOCKERS_RESOLVED.md`):
1. MSSQL → PostgreSQL (DB now works)
2. Fixed `pip install .` (build-backend corrected)
3. Added GitHub Actions CI (quality automated)

✅ **P1 Correctness Fixed** (see `docs/development/P1_COMPLETE.md`):
4. Docs match reality (orchestrator + README updated)
5. Tool planner hardened (better JSON parsing)
6. Loop control improved (error detection + more phrases)
7. Intent routing expanded (more keywords + docs)

## Test The Fixes

### 1. Build and Start
```bash
cd atlas

# Start the stack
docker compose up -d

# Watch logs
docker compose logs -f api
```

**Expected**: All services start, API connects to PostgreSQL (no ODBC errors)

### 2. Initialize Database
```bash
# Run migrations
docker compose exec api alembic upgrade head
```

**Expected**: Migrations apply successfully to PostgreSQL

### 3. Pull AI Models
```bash
# Code generation model
docker compose exec ollama ollama pull qwen2.5-coder:7b

# Embedding model
docker compose exec ollama ollama pull nomic-embed-text
```

**Expected**: Models download and are ready

### 4. Health Check
```bash
curl http://localhost:8000/api/v1/admin/health
```

**Expected**:
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "ollama": "connected"
}
```

### 5. Register a User
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "SecurePass123!",
    "org_id": "test-org"
  }'
```

**Expected**: User created, returns access token

### 6. Test Tool Loop
Open http://localhost:8000/docs and use the chat endpoint with:
```json
{
  "message": "Search for authentication functions and read the main auth file",
  "repo_id": null
}
```

**Expected**: 
- Agent plans tools (search_code, read_file)
- Executes them sequentially
- Returns response with context

### 7. Test Review Loop
```json
{
  "message": "Fix the bug in login validation",
  "repo_id": "<your-repo-id>"
}
```

**Expected**:
- Agent generates fix
- ReviewAgent runs (intent = "fix")
- May request revision if issues found
- Finalizes after approval or max revisions

---

## Verify CI Works

### Push to GitHub
```bash
git add .
git commit -m "P0+P1: PostgreSQL migration, CI, hardened LLM seams, updated docs"
git push origin main
```

**Expected**: GitHub Actions runs automatically:
- ✅ Ruff check passes
- ✅ Black check passes
- ✅ MyPy passes
- ✅ Pytest with 75% coverage passes

Check: https://github.com/your-org/atlas/actions

---

## Manual Test Checklist

### Database (P0 #1):
- [ ] Docker compose starts without ODBC errors
- [ ] API logs show PostgreSQL connection successful
- [ ] Alembic migrations apply cleanly
- [ ] Can create user via API

### Package Build (P0 #2):
```bash
pip install -e .
```
- [ ] Installs without errors
- [ ] Can import: `python -c "from app.main import app; print('OK')"`

### CI Pipeline (P0 #3):
- [ ] Push triggers workflow
- [ ] All quality checks pass
- [ ] Coverage meets 75% threshold
- [ ] Badge shows green

### Documentation (P1 #4):
- [ ] README Architecture section accurate
- [ ] orchestrator.py docstring matches implementation
- [ ] Tool loop described correctly
- [ ] Review loop documented

### LLM Seams (P1 #6):
Test tool planner with edge cases:
```python
# Should handle markdown
response = "```json\n[{\"tool\": \"read_file\"}]\n```"

# Should handle case variations  
response = "JSON\n[{\"tool\": \"read_file\"}]"

# Should log and return [] on invalid JSON
response = "invalid json"
```

### Intent Routing (P1 #10):
Test with various queries:
- [ ] "fix this bug" → intent = "fix"
- [ ] "write tests" → intent = "test"  
- [ ] "review my code" → intent = "review"
- [ ] "explain how this works" → intent = "explain"
- [ ] "find the database code" → intent = "search"
- [ ] "how do I find X" → intent = "explain" (not "search")

---

## Troubleshooting

### PostgreSQL Won't Start
```bash
# Check logs
docker compose logs postgres

# Restart
docker compose restart postgres

# Verify health
docker compose exec postgres pg_isready
```

### API Can't Connect to DB
```bash
# Check environment
docker compose exec api env | grep DB_

# Expected:
# DB_HOST=postgres
# DB_PORT=5432
# DB_USER=postgres
# DB_PASSWORD=postgres
```

### Migrations Fail
```bash
# Check current version
docker compose exec api alembic current

# Stamp head if needed
docker compose exec api alembic stamp head

# Try upgrade again
docker compose exec api alembic upgrade head
```

### Ollama Models Not Found
```bash
# List installed models
docker compose exec ollama ollama list

# If empty, pull again
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull nomic-embed-text
```

### Tests Fail Locally
```bash
# Run with verbose output
pytest -v

# Run specific test
pytest tests/unit/test_tool_planner.py -v

# Check test database
DB_NAME=test_db pytest
```

---

## Success Criteria

### P0 (Blockers):
✅ API starts and connects to PostgreSQL  
✅ `pip install .` works  
✅ CI pipeline runs on push  

### P1 (Correctness):
✅ README accurately describes V1.2 architecture  
✅ Tool planner handles malformed JSON gracefully  
✅ Loop control doesn't get stuck  
✅ Intent routing covers common cases  

### Integration:
⏳ Can register user  
⏳ Can chat with tool-use  
⏳ Review loop triggers for fix intents  
⏳ Memory persists across sessions  

---

## Key URLs

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/api/v1/admin/health
- **Metrics**: http://localhost:8000/api/v1/admin/metrics
- **Grafana**: http://localhost:3001 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Jaeger**: http://localhost:16686
- **ChromaDB**: http://localhost:8001

---

## What's Next

### If Tests Pass:
1. ✅ Mark P0/P1 as complete
2. Deploy to staging
3. Test with real repositories
4. Gather user feedback

### If Tests Fail:
1. Check CI logs for specific failures
2. Fix issues in focused PRs
3. Re-run CI
4. Update this guide with learnings

### P2 Optional Polish:
7. Clean root directory (move *_COMPLETE.md to docs/)
8. Feature branches + PRs workflow
9. MMR similarity upgrade
10. (Moved to V2: LLM intent classification)

---

## Quick Commands Reference

```bash
# Start
docker compose up -d

# Stop
docker compose down

# Rebuild
docker compose build

# Logs
docker compose logs -f api

# Shell into API
docker compose exec api bash

# Run migrations
docker compose exec api alembic upgrade head

# Run tests
docker compose exec api pytest

# Quality checks
docker compose exec api ruff check app tests
docker compose exec api black --check app tests
docker compose exec api mypy app

# Restart service
docker compose restart api

# Check health
curl http://localhost:8000/api/v1/admin/health
```

---

**Status**: Ready to test. All P0/P1 fixes committed and documented.
