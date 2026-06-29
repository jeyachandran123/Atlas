"""
Context builder.

Takes retrieved code chunks and assembles them into a prompt-ready
context block that fits within the model's token budget.

Token budget strategy:
  Total context window (e.g. 32,768 tokens)
  - System prompt:          ~1,000 tokens
  - User message:           ~500 tokens
  - Conversation history:   ~2,000 tokens (last 3 turns)
  - Safety margin:          ~500 tokens
  = Available for code:     ~28,768 tokens

If retrieved chunks exceed the budget:
  1. Always include Priority 1 chunks (directly referenced code)
  2. Include Priority 2 chunks (callers, callees) if budget allows
  3. Compress Priority 3+ chunks to one-line summaries
  4. Omit the rest and note the count
"""

from __future__ import annotations

from typing import Optional

from app.shared.schemas import CodeChunk, ContextWindow, SearchResult

# Token estimates (1 token ≈ 4 characters for code)
CHARS_PER_TOKEN = 4

# Default context window for qwen2.5-coder:7b
DEFAULT_CONTEXT_WINDOW = 32768

# Space reserved for system prompt + user message + history + margin
RESERVED_TOKENS = 4096

# Minimum score threshold — don't include low-relevance chunks
MIN_RELEVANCE_SCORE = 0.3

# Summary template for compressed chunks
SUMMARY_TEMPLATE = "# {path} (lines {start}-{end}) [{chunk_type}: {name}] — compressed\n"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars per token."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def _compress_chunk(chunk: CodeChunk) -> str:
    """
    Compress a low-priority chunk to a one-line summary.
    Saves ~95% of tokens while preserving awareness of the chunk's existence.
    """
    name = chunk.function_name or chunk.class_name or "unnamed"
    return SUMMARY_TEMPLATE.format(
        path=chunk.file_path,
        start=chunk.start_line,
        end=chunk.end_line,
        chunk_type=chunk.chunk_type.value,
        name=name,
    )


class ContextBuilder:
    """
    Assembles retrieved code chunks into a context block.

    Respects token budgets, deduplicates, and compresses low-priority chunks.
    The output is a ContextWindow ready for injection into the prompt.
    """

    def __init__(
        self,
        model_context_window: int = DEFAULT_CONTEXT_WINDOW,
        reserved_tokens: int = RESERVED_TOKENS,
    ) -> None:
        self.available_tokens = model_context_window - reserved_tokens

    def build(
        self,
        results: list[SearchResult],
        focus_file: Optional[str] = None,
    ) -> ContextWindow:
        """
        Build a context window from search results.

        Args:
            results: Ranked search results (highest score first).
            focus_file: If set, chunks from this file are Priority 1.
        """
        if not results:
            return ContextWindow(chunks=[], total_tokens=0, budget_used=0.0)

        # Filter below minimum relevance
        results = [r for r in results if r.score >= MIN_RELEVANCE_SCORE]

        # Deduplicate by chunk identity (same file + same lines)
        seen: set[str] = set()
        deduped: list[SearchResult] = []
        for result in results:
            key = f"{result.chunk.file_path}:{result.chunk.start_line}"
            if key not in seen:
                seen.add(key)
                deduped.append(result)

        # Sort by priority: focus file first, then by score
        def priority(r: SearchResult) -> tuple[int, float]:
            is_focus = 1 if focus_file and r.chunk.file_path == focus_file else 0
            return (-is_focus, -r.score)  # negative for descending sort

        deduped.sort(key=priority)

        # Fill token budget
        selected: list[SearchResult] = []
        compressed: list[SearchResult] = []
        omitted: list[SearchResult] = []
        tokens_used = 0

        for result in deduped:
            chunk_tokens = _estimate_tokens(result.chunk.content)
            header_tokens = _estimate_tokens(result.chunk.display_location) + 5

            if tokens_used + chunk_tokens + header_tokens <= self.available_tokens:
                selected.append(result)
                tokens_used += chunk_tokens + header_tokens
            elif tokens_used + 20 <= self.available_tokens:
                # Add compressed summary instead
                summary_tokens = _estimate_tokens(_compress_chunk(result.chunk))
                if tokens_used + summary_tokens <= self.available_tokens:
                    compressed.append(result)
                    tokens_used += summary_tokens
                else:
                    omitted.append(result)
            else:
                omitted.append(result)

        # Re-rank selected by score for the final output
        for i, r in enumerate(selected):
            r.rank = i + 1

        budget_used = tokens_used / self.available_tokens

        return ContextWindow(
            chunks=selected,
            total_tokens=tokens_used,
            budget_used=min(1.0, budget_used),
            compressed_count=len(compressed),
            omitted_count=len(omitted),
        )

    def format_context_block(self, window: ContextWindow) -> str:
        """
        Format the context window as a string for prompt injection.

        Example output:
            # app/auth/service.py (lines 45-89) — function: verify_token
            ```python
            def verify_token(token: str) -> User:
                ...
            ```
        """
        if not window.chunks:
            return "No relevant code context found."

        parts = []
        for result in window.chunks:
            chunk = result.chunk
            header = f"# {chunk.file_path} (lines {chunk.start_line}-{chunk.end_line})"
            if chunk.function_name:
                header += f" — {chunk.chunk_type.value}: {chunk.function_name}"
            elif chunk.class_name:
                header += f" — {chunk.chunk_type.value}: {chunk.class_name}"
            parts.append(f"{header}\n```{chunk.language}\n{chunk.content}\n```")

        context = "\n\n".join(parts)

        if window.compressed_count or window.omitted_count:
            context += (
                f"\n\n[Context budget: {window.budget_used:.0%} used. "
                f"{window.compressed_count} chunks summarised, "
                f"{window.omitted_count} chunks omitted.]"
            )

        return context
