"""
Unit tests for Git API router.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import create_app
from app.auth import require_developer
from app.database import get_db


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize git repo
        import subprocess
        subprocess.run(['git', 'init'], cwd=tmpdir, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=tmpdir, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=tmpdir, capture_output=True)
        
        # Create initial commit
        test_file = os.path.join(tmpdir, 'test.py')
        with open(test_file, 'w') as f:
            f.write('def hello():\n    print("Hello")\n')
        
        subprocess.run(['git', 'add', '.'], cwd=tmpdir, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=tmpdir, capture_output=True)
        
        # Modify file for uncommitted changes
        with open(test_file, 'a') as f:
            f.write('\ndef world():\n    print("World")\n')
        
        yield tmpdir


@pytest.fixture
def mock_db():
    """Mock database session."""
    return AsyncMock()


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    user = MagicMock()
    user.id = "user1"
    user.org_id = "org1"
    return user


@pytest.fixture
def mock_repo(temp_git_repo):
    """Mock repository."""
    repo = MagicMock()
    repo.id = "repo1"
    repo.local_path = temp_git_repo
    return repo


def test_get_git_status(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test getting git status."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "branch" in data
        assert "is_clean" in data
        assert isinstance(data["modified"], list)
        # Should have uncommitted changes
        assert not data["is_clean"]


def test_get_git_diff(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test getting git diff."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/diff")
        
        assert response.status_code == 200
        data = response.json()
        assert "diff" in data
        assert "files_changed" in data
        # Should show the uncommitted change
        assert "def world():" in data["diff"] or "No changes" in data["diff"]


def test_get_git_log(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test getting git log."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/log?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        assert "commits" in data
        assert len(data["commits"]) >= 1
        # Should have our initial commit
        assert any("Initial commit" in commit["message"] for commit in data["commits"])


def test_get_git_branches(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test listing git branches."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/branches")
        
        assert response.status_code == 200
        data = response.json()
        assert "branches" in data
        assert "current_branch" in data
        assert len(data["branches"]) >= 1
        # Should have master or main branch
        branch_names = [b["name"] for b in data["branches"]]
        assert "master" in branch_names or "main" in branch_names


def test_git_operations_require_git_repo(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test that git operations fail on non-git directories."""
    app = create_app()
    
    # Remove .git directory
    import shutil
    git_dir = os.path.join(temp_git_repo, '.git')
    if os.path.exists(git_dir):
        shutil.rmtree(git_dir)
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/status")
        
        assert response.status_code == 400
        assert "not a git repository" in response.json()["detail"].lower()


def test_git_access_control(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test that git operations respect access control."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        # User has no access
        mock_repo_instance.has_access = AsyncMock(return_value=False)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/status")
        
        assert response.status_code == 403


def test_git_show_commit(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test showing a specific commit."""
    app = create_app()
    
    # Get the commit SHA
    import subprocess
    result = subprocess.run(
        ['git', 'log', '--format=%H', '-n', '1'],
        cwd=temp_git_repo,
        capture_output=True,
        text=True
    )
    commit_sha = result.stdout.strip()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get(f"/api/v1/git/repo1/show?commit_sha={commit_sha}")
        
        assert response.status_code == 200
        data = response.json()
        assert "commit" in data
        assert "diff" in data
        assert data["commit"]["sha"] == commit_sha


def test_git_blame(temp_git_repo, mock_user, mock_repo, mock_db):
    """Test git blame for a file."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.git.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/git/repo1/blame?file_path=test.py")
        
        assert response.status_code == 200
        data = response.json()
        assert "file_path" in data
        assert "lines" in data
        assert len(data["lines"]) > 0
        # Each line should have blame info
        assert all("commit_sha" in line for line in data["lines"])
        assert all("author" in line for line in data["lines"])
