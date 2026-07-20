"""
Version constants — the single source of truth for Knowledge Object
versioning (Objective 5).

Bumping PROCESSING_VERSION or CHUNK_VERSION affects only documents processed
AFTER the bump. Existing Knowledge Objects keep the version they were built
with forever; reprocessing creates knowledge stamped with the current
versions, it never rewrites history's meaning.
"""
from __future__ import annotations

# The processing engine as a whole (orchestrator + stage set).
PROCESSING_VERSION = "1.0.0"

# The chunking algorithm specifically — bump when chunk boundaries change.
CHUNK_VERSION = "1.0.0"

# The Knowledge Object schema shape (structure_json layout, field set).
SCHEMA_VERSION = "1.0.0"

# Fallback when a parser doesn't declare its own `version` attribute.
DEFAULT_PARSER_VERSION = "1.0.0"
