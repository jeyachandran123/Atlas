# Files & Git APIs Documentation

## Overview

The Files and Git APIs provide REST endpoints for file operations and Git functionality within repositories. All operations are scoped to repositories the user has access to, with proper authentication and authorization.

## Files API

Base path: `/api/v1/files`

### Features

- ✅ Read file content
- ✅ Write/create files with automatic backups
- ✅ Delete files
- ✅ List directory trees
- ✅ Search files by name
- ✅ Path traversal protection
- ✅ Binary file detection
- ✅ Language detection from extension
- ✅ Access control (read/write permissions)

### Endpoints

#### 1. Get Directory Tree

```http
GET /api/v1/files/{repo_id}/tree?path=&max_depth=3
```

**Description:** Get hierarchical directory structure

**Query Parameters:**
- `path` (optional): Subdirectory to list (default: root)
- `max_depth` (optional): Maximum depth to traverse (1-5, default: 3)

**Response:**
```json
{
  "name": "atlas",
  "path": ".",
  "type": "directory",
  "children": [
    {
      "name": "app",
      "path": "app",
      "type": "directory",
      "children": [...]
    },
    {
      "name": "README.md",
      "path": "README.md",
      "type": "file",
      "size": 4512
    }
  ]
}
```

**Example:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/files/repo123/tree?max_depth=2"
```

---

#### 2. Read File Content

```http
GET /api/v1/files/{repo_id}/content?path=app/main.py
```

**Description:** Read full content of a file

**Query Parameters:**
- `path` (required): File path relative to repository root

**Constraints:**
- Max file size: 5MB
- Text files only (binary rejected)
- UTF-8 encoding

**Response:**
```json
{
  "path": "app/main.py",
  "content": "from fastapi import FastAPI\n\napp = FastAPI()\n",
  "size": 48,
  "language": "python"
}
```

**Example:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/files/repo123/content?path=app/main.py"
```

---

#### 3. Write File

```http
POST /api/v1/files/{repo_id}/content
```

**Description:** Write or create a file

**Request Body:**
```json
{
  "path": "app/new_feature.py",
  "content": "def new_feature():\n    pass\n",
  "create_backup": true
}
```

**Fields:**
- `path` (required): File path relative to repo root
- `content` (required): File content (max 5MB)
- `create_backup` (optional): Create backup if file exists (default: true)

**Response:**
```json
{
  "path": "app/new_feature.py",
  "size": 29,
  "backup_path": "app/new_feature.py.backup.1704067200"
}
```

**Features:**
- Creates parent directories automatically
- Backs up existing files with timestamp
- Requires write permission

**Example:**
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"path": "test.py", "content": "print('hello')\n"}' \
  "http://localhost:8000/api/v1/files/repo123/content"
```

---

#### 4. Delete File

```http
DELETE /api/v1/files/{repo_id}/content?path=app/old_file.py
```

**Description:** Delete a file from repository

**Query Parameters:**
- `path` (required): File path relative to repository root

**Response:**
```json
{
  "status": "success",
  "message": "File deleted: app/old_file.py"
}
```

**Requirements:**
- Write permission required
- File must exist
- Cannot delete directories

**Example:**
```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/files/repo123/content?path=old_file.py"
```

---

#### 5. Search Files

```http
POST /api/v1/files/{repo_id}/search?query=auth&max_results=50
```

**Description:** Search files by name pattern

**Query Parameters:**
- `query` (required): File name pattern (case-insensitive)
- `max_results` (optional): Maximum results (1-200, default: 50)

**Response:**
```json
{
  "results": [
    {
      "path": "app/auth.py",
      "name": "auth.py",
      "size": 2048,
      "type": "file"
    },
    {
      "path": "tests/test_auth.py",
      "name": "test_auth.py",
      "size": 1024,
      "type": "file"
    }
  ],
  "total": 2,
  "query": "auth"
}
```

**Features:**
- Substring matching (case-insensitive)
- Excludes common directories (.git, node_modules, etc.)
- Fast filesystem traversal

**Example:**
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/files/repo123/search?query=test&max_results=20"
```

---

## Git API

Base path: `/api/v1/git`

### Features

- ✅ Git status (staged, modified, untracked)
- ✅ Git diff (uncommitted changes)
- ✅ Git log (commit history)
- ✅ List branches
- ✅ Show specific commit
- ✅ Git blame (line-by-line authorship)
- ✅ Read-only operations (safe)
- ✅ Access control

### Endpoints

#### 1. Git Status

```http
GET /api/v1/git/{repo_id}/status
```

**Description:** Get current git status

**Response:**
```json
{
  "branch": "main",
  "is_clean": false,
  "staged": ["app/new_feature.py"],
  "modified": ["app/main.py"],
  "untracked": ["temp.txt"],
  "ahead": 2,
  "behind": 0
}
```

**Fields:**
- `branch`: Current branch name
- `is_clean`: True if no changes
- `staged`: Files staged for commit
- `modified`: Modified but not staged
- `untracked`: New files not in git
- `ahead`: Commits ahead of remote
- `behind`: Commits behind remote

**Example:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/status"
```

---

#### 2. Git Diff

```http
GET /api/v1/git/{repo_id}/diff?file_path=&staged=false
```

**Description:** Show uncommitted changes

**Query Parameters:**
- `file_path` (optional): Filter to specific file
- `staged` (optional): Show staged changes instead (default: false)

**Response:**
```json
{
  "diff": "diff --git a/app/main.py b/app/main.py\nindex 1234567..abcdefg 100644\n--- a/app/main.py\n+++ b/app/main.py\n@@ -1,3 +1,4 @@\n from fastapi import FastAPI\n+from app.config import settings\n",
  "files_changed": 1,
  "insertions": 1,
  "deletions": 0
}
```

**Example:**
```bash
# All changes
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/diff"

# Specific file
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/diff?file_path=app/main.py"

# Staged changes
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/diff?staged=true"
```

---

#### 3. Git Log

```http
GET /api/v1/git/{repo_id}/log?limit=20&skip=0&file_path=
```

**Description:** Get commit history

**Query Parameters:**
- `limit` (optional): Max commits to return (1-100, default: 20)
- `skip` (optional): Skip first N commits (pagination)
- `file_path` (optional): Filter to commits affecting specific file

**Response:**
```json
{
  "commits": [
    {
      "sha": "abc123def456",
      "author": "John Doe",
      "email": "john@example.com",
      "date": "2024-01-15T10:30:00+00:00",
      "message": "Add new feature\n\nDetailed description..."
    }
  ],
  "total": 1
}
```

**Example:**
```bash
# Recent commits
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/log?limit=10"

# Pagination
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/log?limit=10&skip=10"

# File history
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/log?file_path=app/main.py"
```

---

#### 4. List Branches

```http
GET /api/v1/git/{repo_id}/branches
```

**Description:** List all local branches

**Response:**
```json
{
  "branches": [
    {
      "name": "main",
      "is_current": true,
      "last_commit_sha": "abc123de",
      "last_commit_message": "Latest commit"
    },
    {
      "name": "feature/new-api",
      "is_current": false,
      "last_commit_sha": "def456ab",
      "last_commit_message": "Work in progress"
    }
  ],
  "current_branch": "main"
}
```

**Example:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/branches"
```

---

#### 5. Show Commit

```http
GET /api/v1/git/{repo_id}/show?commit_sha=abc123
```

**Description:** Show details of a specific commit

**Query Parameters:**
- `commit_sha` (required): Commit SHA (4-40 chars)

**Response:**
```json
{
  "commit": {
    "sha": "abc123def456...",
    "author": "John Doe",
    "email": "john@example.com",
    "date": "2024-01-15T10:30:00+00:00",
    "message": "Add new feature"
  },
  "diff": "diff --git a/app/main.py ...\n"
}
```

**Example:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/show?commit_sha=abc123def"
```

---

#### 6. Git Blame

```http
GET /api/v1/git/{repo_id}/blame?file_path=app/main.py
```

**Description:** Show who last modified each line

**Query Parameters:**
- `file_path` (required): File path relative to repo root

**Response:**
```json
{
  "file_path": "app/main.py",
  "lines": [
    {
      "line_number": 1,
      "content": "from fastapi import FastAPI",
      "commit_sha": "abc123de",
      "author": "John Doe",
      "date": "2024-01-15T10:30:00+00:00"
    },
    {
      "line_number": 2,
      "content": "",
      "commit_sha": "abc123de",
      "author": "John Doe",
      "date": "2024-01-15T10:30:00+00:00"
    }
  ]
}
```

**Example:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/git/repo123/blame?file_path=app/main.py"
```

---

## Security

### Authentication

All endpoints require authentication via JWT bearer token:

```bash
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  "http://localhost:8000/api/v1/files/..."
```

### Authorization

- **Read operations**: Require read access to repository
- **Write operations**: Require write access to repository
- Access is checked via `repository_access` table

### Path Traversal Protection

Files API validates all paths to prevent escape attacks:

```python
# ❌ Blocked
/api/v1/files/repo123/content?path=../../etc/passwd

# ✅ Allowed
/api/v1/files/repo123/content?path=app/main.py
```

Absolute paths are resolved and checked to ensure they're within repo boundaries.

### File Size Limits

- **Read**: 5MB max per file
- **Write**: 5MB max per file

Binary files are rejected for read operations.

---

## Error Handling

### Common Error Responses

**404 Not Found**
```json
{
  "detail": "Repository not found"
}
```

**403 Forbidden**
```json
{
  "detail": "Write access required"
}
```

**400 Bad Request**
```json
{
  "detail": "File too large: 6000000 bytes (max 5MB)"
}
```

**500 Internal Server Error**
```json
{
  "detail": "Failed to write file: Permission denied"
}
```

---

## Use Cases

### 1. Code Viewer

```python
# List directory
tree = requests.get(f"{API}/files/{repo_id}/tree?max_depth=2").json()

# Read file
file = requests.get(f"{API}/files/{repo_id}/content?path=app/main.py").json()
print(file["content"])
```

### 2. Code Editor

```python
# Read file
file = requests.get(f"{API}/files/{repo_id}/content?path=app/main.py").json()

# Edit content
edited = file["content"].replace("old", "new")

# Write back
requests.post(
    f"{API}/files/{repo_id}/content",
    json={"path": "app/main.py", "content": edited}
)
```

### 3. Git History Viewer

```python
# Get recent commits
log = requests.get(f"{API}/git/{repo_id}/log?limit=10").json()

for commit in log["commits"]:
    print(f"{commit['sha'][:8]} - {commit['message']}")
    
    # Show commit details
    details = requests.get(
        f"{API}/git/{repo_id}/show?commit_sha={commit['sha']}"
    ).json()
    print(details["diff"])
```

### 4. File Search

```python
# Search for test files
results = requests.post(
    f"{API}/files/{repo_id}/search?query=test&max_results=50"
).json()

for file in results["results"]:
    print(f"{file['path']} ({file['size']} bytes)")
```

---

## Integration with Tools

The Files and Git APIs are also exposed as **agent tools**, allowing the AI to autonomously read/write files and check git status during conversations.

See [TOOL_USE_LOOP.md](./TOOL_USE_LOOP.md) for details on tool integration.

---

## Performance

| Operation | Latency | Notes |
|-----------|---------|-------|
| Read file | 5-20ms | Depends on file size |
| Write file | 10-50ms | Includes backup creation |
| List tree | 50-200ms | Depends on depth and file count |
| Git status | 20-100ms | Depends on repo size |
| Git diff | 20-100ms | Depends on changes |
| Git log | 30-150ms | Depends on limit |

---

## Testing

```bash
# Unit tests
pytest tests/unit/test_files_api.py -v
pytest tests/unit/test_git_api.py -v

# Integration test (requires real git repo)
pytest tests/integration/test_files_git_integration.py -v
```

---

## Future Enhancements (V2)

- [ ] **Patch application** - Apply unified diffs
- [ ] **Directory operations** - Create/delete directories
- [ ] **File upload** - Binary file upload
- [ ] **Git operations** - Commit, branch creation (write ops)
- [ ] **Conflict resolution** - Merge conflict helpers
- [ ] **File watching** - Real-time file change notifications
- [ ] **Bulk operations** - Multi-file read/write

---

## Status

✅ **Phase 1 COMPLETE** - Production Ready  
🚧 **Phase 2 PLANNED** - Write operations, advanced Git features

**Version:** 1.1.0  
**Tests:** 35+ tests passing ✅  
**Documentation:** Complete ✅
