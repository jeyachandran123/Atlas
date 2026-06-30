"""
Unit tests for Files API router.
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import create_app
from app.auth import require_developer
from app.database import get_db


@pytest.fixture
def temp_repo():
    """Create a temporary repository directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, 'w') as f:
            f.write("def hello():\n    print('Hello')\n")
        
        # Create subdirectory
        subdir = os.path.join(tmpdir, "subdir")
        os.makedirs(subdir)
        sub_file = os.path.join(subdir, "sub.js")
        with open(sub_file, 'w') as f:
            f.write("console.log('test');\n")
        
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
def mock_repo(temp_repo):
    """Mock repository."""
    repo = MagicMock()
    repo.id = "repo1"
    repo.local_path = temp_repo
    return repo


def test_get_file_tree(temp_repo, mock_user, mock_repo, mock_db):
    """Test getting directory tree."""
    app = create_app()
    
    # Override dependencies
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/files/repo1/tree")
        
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "directory"
        assert data["children"] is not None
        # Should contain our test files
        file_names = [child["name"] for child in data["children"]]
        assert "test.py" in file_names
        assert "subdir" in file_names


def test_read_file(temp_repo, mock_user, mock_repo, mock_db):
    """Test reading file content."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/files/repo1/content?path=test.py")
        
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "test.py"
        assert "def hello():" in data["content"]
        assert data["language"] == "python"


def test_read_file_not_found(temp_repo, mock_user, mock_repo, mock_db):
    """Test reading non-existent file."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.get("/api/v1/files/repo1/content?path=nonexistent.py")
        
        assert response.status_code == 404


def test_write_file(temp_repo, mock_user, mock_repo, mock_db):
    """Test writing file content."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.post(
            "/api/v1/files/repo1/content",
            json={
                "path": "new_file.py",
                "content": "def new():\n    pass\n",
                "create_backup": False,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "new_file.py"
        
        # Verify file was created
        new_file_path = os.path.join(temp_repo, "new_file.py")
        assert os.path.exists(new_file_path)
        with open(new_file_path, 'r') as f:
            content = f.read()
            assert "def new():" in content


def test_write_file_creates_backup(temp_repo, mock_user, mock_repo, mock_db):
    """Test that writing to existing file creates backup."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        # Write to existing file with backup
        response = client.post(
            "/api/v1/files/repo1/content",
            json={
                "path": "test.py",
                "content": "def modified():\n    pass\n",
                "create_backup": True,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["backup_path"] is not None
        assert ".backup." in data["backup_path"]


def test_delete_file(temp_repo, mock_user, mock_repo, mock_db):
    """Test deleting a file."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        # Verify file exists
        test_file = os.path.join(temp_repo, "test.py")
        assert os.path.exists(test_file)
        
        response = client.delete("/api/v1/files/repo1/content?path=test.py")
        
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        
        # Verify file was deleted
        assert not os.path.exists(test_file)


def test_search_files(temp_repo, mock_user, mock_repo, mock_db):
    """Test searching for files by name."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        response = client.post("/api/v1/files/repo1/search?query=test")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0
        assert len(data["results"]) > 0
        # Should find test.py
        file_names = [r["name"] for r in data["results"]]
        assert "test.py" in file_names


def test_path_traversal_protection(temp_repo, mock_user, mock_repo, mock_db):
    """Test that path traversal attacks are blocked."""
    app = create_app()
    
    app.dependency_overrides[require_developer] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    client = TestClient(app)
    
    with patch('app.api.v1.files.router.RepositoryRepo') as mock_repo_repo:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
        mock_repo_instance.has_access = AsyncMock(return_value=True)
        mock_repo_repo.return_value = mock_repo_instance
        
        # Try to read outside repo
        response = client.get("/api/v1/files/repo1/content?path=../../etc/passwd")
        
        assert response.status_code == 403
        assert "escapes repository" in response.json()["detail"].lower()
