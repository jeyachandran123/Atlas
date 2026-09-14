"""Natural-language document tasks: understand, write code, run it, verify it.

The layer exists because the generation pipeline builds documents from a
ContentModel capped at 2000 rows and 50 columns, which cannot express a real
transform of a 1251-row, 77-column sheet - and because no model can be asked to
emit a quarter of a million cells. Here the model writes the program and the
program writes the cells.
"""

from app.document_platform.execution.introspect import DocumentStructure, introspect
from app.document_platform.execution.preview import ResultPreview, preview_output
from app.document_platform.execution.runner import DocumentTaskRunner, TaskResult
from app.document_platform.execution.sandbox import SandboxUnavailableError, docker_available

__all__ = [
    "DocumentStructure",
    "DocumentTaskRunner",
    "ResultPreview",
    "SandboxUnavailableError",
    "TaskResult",
    "docker_available",
    "introspect",
    "preview_output",
]
