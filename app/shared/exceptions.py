"""
Domain exceptions.

Each exception maps to an HTTP status code.
FastAPI exception handlers in main.py convert these automatically.
"""

from __future__ import annotations


class AIAssistantError(Exception):
    """Base exception for all domain errors."""

    http_status: int = 500
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.message
        super().__init__(self.message)


class NotFoundError(AIAssistantError):
    http_status = 404
    message = "Resource not found"


class UnauthorizedError(AIAssistantError):
    http_status = 401
    message = "Authentication required"


class ForbiddenError(AIAssistantError):
    http_status = 403
    message = "Access denied"


class ValidationError(AIAssistantError):
    http_status = 422
    message = "Validation failed"


class ConflictError(AIAssistantError):
    http_status = 409
    message = "Resource already exists"


class RepositoryNotFoundError(NotFoundError):
    message = "Repository not found"


class RepositoryNotIndexedError(AIAssistantError):
    http_status = 400
    message = "Repository is not indexed yet. Trigger indexing first."


class IndexJobNotFoundError(NotFoundError):
    message = "Index job not found"


class ConversationNotFoundError(NotFoundError):
    message = "Conversation not found"


class OllamaUnavailableError(AIAssistantError):
    http_status = 503
    message = "AI model (Ollama) is not available. Ensure Ollama is running."


class IndexingInProgressError(AIAssistantError):
    http_status = 409
    message = "Indexing is already in progress for this repository"


class FileSafetyError(AIAssistantError):
    http_status = 400
    message = "File operation rejected for security reasons"


class PathTraversalError(FileSafetyError):
    message = "Path traversal detected — operation rejected"


class ToolExecutionError(AIAssistantError):
    http_status = 500
    message = "Tool execution failed"
