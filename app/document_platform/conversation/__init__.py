"""
Conversational Knowledge Intelligence (Phase 4).

Grounded question answering over the Knowledge Platform, consuming knowledge
exclusively through the Semantic Platform's public interfaces (embedding
provider + vector store search). Every layer here has one responsibility:

    gateway → intent → planner → retrieval → ranking → context_builder
    → prompts → reasoning (llm) → citations → validator → streaming
    → memory / events / metrics

Nothing in this package modifies the frozen Knowledge or Semantic platforms.
"""
