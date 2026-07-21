"""
Version constants for the Semantic layer (Objective 13) — the semantic
counterpart of processing/versioning.py, kept separate since that file is
part of the frozen Phase 2 pipeline.

Bumping any of these affects only embeddings generated AFTER the bump.
Existing embedding_records keep the version they were generated with
forever — reprocessing/re-embedding creates new records stamped with
current versions; it never rewrites history's meaning. This is what lets
multiple embedding versions coexist (a hard requirement of Objective 13).
"""
from __future__ import annotations

EMBEDDING_VERSION = "1.0.0"     # the semantic pipeline as a whole
VECTOR_VERSION = "1.0.0"        # the vector representation/storage format
SCHEMA_VERSION = "1.0.0"        # semantic_manifests / embedding_records shape

# Fallbacks when a provider/model doesn't declare its own version.
DEFAULT_PROVIDER_VERSION = "1.0.0"
DEFAULT_MODEL_VERSION = "1.0.0"
