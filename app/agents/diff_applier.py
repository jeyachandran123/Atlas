"""
Robust diff applier for LLM-generated code changes.

Handles multiple diff formats:
1. Unified diff format (--- +++)
2. Search/replace blocks (<<<<<<< SEARCH / ======= / >>>>>>> REPLACE)
3. Markdown code blocks with file paths

Design principles:
- Fuzzy matching for whitespace tolerance
- Clear error messages with line numbers
- Dry-run mode for validation
- Multiple strategies (exact match → fuzzy match → line-by-line)
- Detailed diff reports

Why not use `patch` library:
- LLM output is often not standard unified diff format
- Need custom handling for markdown code blocks
- Require fuzzy matching for whitespace variations
- Need better error messages for LLM feedback loop
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger


class DiffFormat(Enum):
    """Supported diff formats."""
    UNIFIED = "unified"           # Standard unified diff
    SEARCH_REPLACE = "search_replace"  # <<<<<<< SEARCH / >>>>>>> REPLACE
    MARKDOWN_CODE = "markdown_code"    # ```python:path/to/file.py
    FULL_FILE = "full_file"       # Complete file replacement


class MatchStrategy(Enum):
    """Matching strategies for applying patches."""
    EXACT = "exact"                # Exact string match
    FUZZY_WHITESPACE = "fuzzy_whitespace"  # Ignore whitespace differences
    FUZZY_LINES = "fuzzy_lines"    # Match similar lines with tolerance
    CONTEXTUAL = "contextual"      # Use surrounding context for matching


@dataclass
class DiffHunk:
    """A single change block in a diff."""
    old_start: int  # Starting line in original file (1-indexed)
    old_count: int  # Number of lines in original
    new_start: int  # Starting line in patched file (1-indexed)
    new_count: int  # Number of lines in patched
    old_lines: list[str]  # Lines to remove (without '-' prefix)
    new_lines: list[str]  # Lines to add (without '+' prefix)
    context_before: list[str]  # Lines before the change
    context_after: list[str]   # Lines after the change


@dataclass
class SearchReplaceBlock:
    """A search/replace block."""
    search_text: str
    replace_text: str
    occurrence: int = 1  # Which occurrence to replace (1-indexed)


@dataclass
class ApplyResult:
    """Result of applying a diff."""
    success: bool
    patched_content: str
    original_content: str
    error: Optional[str] = None
    hunks_applied: int = 0
    hunks_failed: int = 0
    strategy_used: Optional[MatchStrategy] = None
    details: list[str] = None

    def __post_init__(self):
        if self.details is None:
            self.details = []


class DiffApplier:
    """
    Robust diff applier with multiple strategies and formats.
    
    Usage:
        applier = DiffApplier()
        result = applier.apply(original_content, diff_text)
        if result.success:
            write_file(result.patched_content)
    """

    def __init__(self, fuzzy_threshold: float = 0.8):
        """
        Initialize diff applier.
        
        Args:
            fuzzy_threshold: Similarity threshold for fuzzy matching (0.0-1.0)
        """
        self.fuzzy_threshold = fuzzy_threshold

    def apply(
        self,
        original: str,
        diff_text: str,
        dry_run: bool = False,
        prefer_strategy: Optional[MatchStrategy] = None,
    ) -> ApplyResult:
        """
        Apply a diff to original content.
        
        Args:
            original: Original file content
            diff_text: Diff in any supported format
            dry_run: If True, validate without applying
            prefer_strategy: Preferred matching strategy
        
        Returns:
            ApplyResult with patched content or error
        """
        # Detect diff format
        diff_format = self._detect_format(diff_text)
        logger.debug(f"Detected diff format: {diff_format}")

        # Apply based on format
        if diff_format == DiffFormat.UNIFIED:
            return self._apply_unified_diff(original, diff_text, dry_run, prefer_strategy)
        elif diff_format == DiffFormat.SEARCH_REPLACE:
            return self._apply_search_replace(original, diff_text, dry_run)
        elif diff_format == DiffFormat.MARKDOWN_CODE:
            return self._apply_markdown_code(original, diff_text, dry_run)
        elif diff_format == DiffFormat.FULL_FILE:
            return self._apply_full_file(original, diff_text, dry_run)
        else:
            return ApplyResult(
                success=False,
                patched_content=original,
                original_content=original,
                error=f"Unsupported diff format: {diff_format}",
            )

    def _detect_format(self, diff_text: str) -> DiffFormat:
        """Detect the format of the diff text."""
        lines = diff_text.strip().split("\n")
        
        # Check for unified diff
        if any(line.startswith("--- ") or line.startswith("+++ ") for line in lines[:5]):
            return DiffFormat.UNIFIED
        
        # Check for search/replace blocks
        if "<<<<<<< SEARCH" in diff_text and ">>>>>>> REPLACE" in diff_text:
            return DiffFormat.SEARCH_REPLACE
        
        # Check for markdown code blocks with file path
        if re.search(r"```\w+:[^\n]+\n", diff_text):
            return DiffFormat.MARKDOWN_CODE
        
        # Check if it's just a complete code block (assume full file)
        if diff_text.strip().startswith("```") and diff_text.strip().endswith("```"):
            return DiffFormat.FULL_FILE
        
        # Default to unified diff
        return DiffFormat.UNIFIED

    def _apply_unified_diff(
        self,
        original: str,
        diff_text: str,
        dry_run: bool,
        prefer_strategy: Optional[MatchStrategy],
    ) -> ApplyResult:
        """Apply a unified diff patch."""
        # Parse hunks
        hunks = self._parse_unified_diff(diff_text)
        if not hunks:
            return ApplyResult(
                success=False,
                patched_content=original,
                original_content=original,
                error="No valid hunks found in diff",
            )

        # Try strategies in order
        strategies = [prefer_strategy] if prefer_strategy else [
            MatchStrategy.EXACT,
            MatchStrategy.FUZZY_WHITESPACE,
            MatchStrategy.CONTEXTUAL,
            MatchStrategy.FUZZY_LINES,
        ]

        for strategy in strategies:
            if strategy is None:
                continue
            
            result = self._apply_hunks_with_strategy(original, hunks, strategy, dry_run)
            if result.success:
                result.strategy_used = strategy
                return result

        # All strategies failed
        return ApplyResult(
            success=False,
            patched_content=original,
            original_content=original,
            error=f"Failed to apply {len(hunks)} hunk(s) with all strategies",
            hunks_failed=len(hunks),
        )

    def _parse_unified_diff(self, diff_text: str) -> list[DiffHunk]:
        """Parse unified diff format into hunks."""
        hunks = []
        lines = diff_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            
            # Look for hunk header: @@ -old_start,old_count +new_start,new_count @@
            if line.startswith("@@"):
                match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if match:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_count = int(match.group(4)) if match.group(4) else 1
                    
                    # Collect hunk lines
                    i += 1
                    old_lines = []
                    new_lines = []
                    context_before = []
                    context_after = []
                    
                    while i < len(lines) and not lines[i].startswith("@@"):
                        hunk_line = lines[i]
                        
                        if hunk_line.startswith("-"):
                            old_lines.append(hunk_line[1:])
                        elif hunk_line.startswith("+"):
                            new_lines.append(hunk_line[1:])
                        elif hunk_line.startswith(" "):
                            # Context line
                            if not old_lines and not new_lines:
                                context_before.append(hunk_line[1:])
                            else:
                                context_after.append(hunk_line[1:])
                        
                        i += 1
                    
                    hunks.append(DiffHunk(
                        old_start=old_start,
                        old_count=old_count,
                        new_start=new_start,
                        new_count=new_count,
                        old_lines=old_lines,
                        new_lines=new_lines,
                        context_before=context_before,
                        context_after=context_after,
                    ))
                    continue
            
            i += 1

        return hunks

    def _apply_hunks_with_strategy(
        self,
        original: str,
        hunks: list[DiffHunk],
        strategy: MatchStrategy,
        dry_run: bool,
    ) -> ApplyResult:
        """Apply hunks using a specific matching strategy."""
        lines = original.splitlines(keepends=True)
        details = []
        hunks_applied = 0
        hunks_failed = 0

        # Sort hunks by line number (descending) to avoid line number shifts
        sorted_hunks = sorted(hunks, key=lambda h: h.old_start, reverse=True)

        for hunk in sorted_hunks:
            try:
                if strategy == MatchStrategy.EXACT:
                    lines = self._apply_hunk_exact(lines, hunk)
                elif strategy == MatchStrategy.FUZZY_WHITESPACE:
                    lines = self._apply_hunk_fuzzy_whitespace(lines, hunk)
                elif strategy == MatchStrategy.CONTEXTUAL:
                    lines = self._apply_hunk_contextual(lines, hunk)
                elif strategy == MatchStrategy.FUZZY_LINES:
                    lines = self._apply_hunk_fuzzy_lines(lines, hunk)
                
                hunks_applied += 1
                details.append(f"✓ Applied hunk at line {hunk.old_start}")
                
            except Exception as e:
                hunks_failed += 1
                details.append(f"✗ Failed hunk at line {hunk.old_start}: {str(e)}")
                logger.warning(f"Hunk application failed: {e}")

        if hunks_failed > 0:
            return ApplyResult(
                success=False,
                patched_content="".join(lines),
                original_content=original,
                error=f"Failed to apply {hunks_failed}/{len(hunks)} hunk(s)",
                hunks_applied=hunks_applied,
                hunks_failed=hunks_failed,
                details=details,
            )

        patched = "".join(lines)
        
        return ApplyResult(
            success=True,
            patched_content=patched if not dry_run else original,
            original_content=original,
            hunks_applied=hunks_applied,
            hunks_failed=hunks_failed,
            details=details,
        )

    def _apply_hunk_exact(self, lines: list[str], hunk: DiffHunk) -> list[str]:
        """Apply hunk with exact string matching."""
        # Find exact match for old lines
        start_idx = hunk.old_start - 1  # Convert to 0-indexed
        
        if start_idx < 0 or start_idx >= len(lines):
            raise ValueError(f"Line {hunk.old_start} out of range")
        
        # Check if old lines match exactly
        for i, old_line in enumerate(hunk.old_lines):
            line_idx = start_idx + i
            if line_idx >= len(lines):
                raise ValueError(f"Not enough lines to match hunk")
            
            if lines[line_idx].rstrip("\n") != old_line.rstrip("\n"):
                raise ValueError(f"Line {line_idx + 1} doesn't match: expected '{old_line.strip()}', got '{lines[line_idx].strip()}'")
        
        # Remove old lines and insert new ones
        for _ in range(len(hunk.old_lines)):
            lines.pop(start_idx)
        
        for i, new_line in enumerate(hunk.new_lines):
            if not new_line.endswith("\n"):
                new_line += "\n"
            lines.insert(start_idx + i, new_line)
        
        return lines

    def _apply_hunk_fuzzy_whitespace(self, lines: list[str], hunk: DiffHunk) -> list[str]:
        """Apply hunk ignoring whitespace differences."""
        start_idx = hunk.old_start - 1
        
        # Normalize whitespace for comparison
        def normalize(s: str) -> str:
            return " ".join(s.split())
        
        # Check if old lines match (ignoring whitespace)
        for i, old_line in enumerate(hunk.old_lines):
            line_idx = start_idx + i
            if line_idx >= len(lines):
                raise ValueError(f"Not enough lines to match hunk")
            
            if normalize(lines[line_idx]) != normalize(old_line):
                raise ValueError(f"Line {line_idx + 1} doesn't match (fuzzy whitespace)")
        
        # Remove old lines and insert new ones
        for _ in range(len(hunk.old_lines)):
            lines.pop(start_idx)
        
        for i, new_line in enumerate(hunk.new_lines):
            if not new_line.endswith("\n"):
                new_line += "\n"
            lines.insert(start_idx + i, new_line)
        
        return lines

    def _apply_hunk_contextual(self, lines: list[str], hunk: DiffHunk) -> list[str]:
        """Apply hunk using surrounding context for matching."""
        # Search for the hunk using context
        search_window = 50  # Lines to search around expected position
        start_search = max(0, hunk.old_start - search_window)
        end_search = min(len(lines), hunk.old_start + search_window)
        
        best_match_idx = None
        best_score = 0.0
        
        for i in range(start_search, end_search):
            # Calculate similarity with context
            score = self._calculate_context_similarity(lines, i, hunk)
            if score > best_score and score >= self.fuzzy_threshold:
                best_score = score
                best_match_idx = i
        
        if best_match_idx is None:
            raise ValueError(f"No contextual match found for hunk at line {hunk.old_start}")
        
        # Apply at best match location
        for _ in range(len(hunk.old_lines)):
            lines.pop(best_match_idx)
        
        for i, new_line in enumerate(hunk.new_lines):
            if not new_line.endswith("\n"):
                new_line += "\n"
            lines.insert(best_match_idx + i, new_line)
        
        return lines

    def _apply_hunk_fuzzy_lines(self, lines: list[str], hunk: DiffHunk) -> list[str]:
        """Apply hunk using fuzzy line matching."""
        # Search for best matching sequence
        search_window = 100
        start_search = max(0, hunk.old_start - search_window)
        end_search = min(len(lines) - len(hunk.old_lines) + 1, hunk.old_start + search_window)
        
        best_match_idx = None
        best_ratio = 0.0
        
        for i in range(start_search, end_search):
            # Compare sequences
            original_seq = [line.strip() for line in lines[i:i + len(hunk.old_lines)]]
            hunk_seq = [line.strip() for line in hunk.old_lines]
            
            matcher = difflib.SequenceMatcher(None, original_seq, hunk_seq)
            ratio = matcher.ratio()
            
            if ratio > best_ratio and ratio >= self.fuzzy_threshold:
                best_ratio = ratio
                best_match_idx = i
        
        if best_match_idx is None:
            raise ValueError(f"No fuzzy match found for hunk at line {hunk.old_start} (best ratio: {best_ratio:.2f})")
        
        # Apply at best match location
        for _ in range(len(hunk.old_lines)):
            lines.pop(best_match_idx)
        
        for i, new_line in enumerate(hunk.new_lines):
            if not new_line.endswith("\n"):
                new_line += "\n"
            lines.insert(best_match_idx + i, new_line)
        
        return lines

    def _calculate_context_similarity(self, lines: list[str], pos: int, hunk: DiffHunk) -> float:
        """Calculate similarity score using context before and after."""
        context_size = 3
        scores = []
        
        # Check context before
        if hunk.context_before:
            before_start = max(0, pos - len(hunk.context_before))
            for i, context_line in enumerate(hunk.context_before):
                line_idx = before_start + i
                if line_idx < len(lines):
                    score = difflib.SequenceMatcher(None, lines[line_idx].strip(), context_line.strip()).ratio()
                    scores.append(score)
        
        # Check main content
        for i, old_line in enumerate(hunk.old_lines):
            line_idx = pos + i
            if line_idx < len(lines):
                score = difflib.SequenceMatcher(None, lines[line_idx].strip(), old_line.strip()).ratio()
                scores.append(score)
        
        # Check context after
        if hunk.context_after:
            after_start = pos + len(hunk.old_lines)
            for i, context_line in enumerate(hunk.context_after):
                line_idx = after_start + i
                if line_idx < len(lines):
                    score = difflib.SequenceMatcher(None, lines[line_idx].strip(), context_line.strip()).ratio()
                    scores.append(score)
        
        return sum(scores) / len(scores) if scores else 0.0

    def _apply_search_replace(self, original: str, diff_text: str, dry_run: bool) -> ApplyResult:
        """Apply search/replace blocks."""
        blocks = self._parse_search_replace(diff_text)
        if not blocks:
            return ApplyResult(
                success=False,
                patched_content=original,
                original_content=original,
                error="No valid search/replace blocks found",
            )

        patched = original
        details = []
        
        for i, block in enumerate(blocks):
            # Count occurrences
            count = patched.count(block.search_text)
            if count == 0:
                return ApplyResult(
                    success=False,
                    patched_content=original,
                    original_content=original,
                    error=f"Search text not found in block {i + 1}: '{block.search_text[:50]}...'",
                    details=details,
                )
            
            if count > 1 and block.occurrence > count:
                return ApplyResult(
                    success=False,
                    patched_content=original,
                    original_content=original,
                    error=f"Block {i + 1} specifies occurrence {block.occurrence}, but only {count} found",
                    details=details,
                )
            
            # Replace nth occurrence
            if block.occurrence == 1 and count == 1:
                patched = patched.replace(block.search_text, block.replace_text, 1)
            else:
                # Replace specific occurrence
                parts = patched.split(block.search_text)
                if block.occurrence <= len(parts) - 1:
                    patched = block.search_text.join(
                        parts[:block.occurrence] + [block.replace_text] + parts[block.occurrence + 1:]
                    )
            
            details.append(f"✓ Applied search/replace block {i + 1} (occurrence {block.occurrence}/{count})")

        return ApplyResult(
            success=True,
            patched_content=patched if not dry_run else original,
            original_content=original,
            hunks_applied=len(blocks),
            details=details,
            strategy_used=MatchStrategy.EXACT,
        )

    def _parse_search_replace(self, diff_text: str) -> list[SearchReplaceBlock]:
        """Parse search/replace blocks from diff text."""
        blocks = []
        
        # Pattern: <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE
        pattern = r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE"
        matches = re.finditer(pattern, diff_text, re.DOTALL)
        
        for match in matches:
            search_text = match.group(1)
            replace_text = match.group(2)
            blocks.append(SearchReplaceBlock(
                search_text=search_text,
                replace_text=replace_text,
            ))
        
        return blocks

    def _apply_markdown_code(self, original: str, diff_text: str, dry_run: bool) -> ApplyResult:
        """Apply markdown code block (extract code from markdown)."""
        # Extract code from markdown: ```language:path
        pattern = r"```\w+:[^\n]+\n(.*?)```"
        match = re.search(pattern, diff_text, re.DOTALL)
        
        if not match:
            return ApplyResult(
                success=False,
                patched_content=original,
                original_content=original,
                error="No valid markdown code block found",
            )
        
        new_content = match.group(1)
        
        return ApplyResult(
            success=True,
            patched_content=new_content if not dry_run else original,
            original_content=original,
            hunks_applied=1,
            details=["✓ Replaced entire file with markdown code block content"],
            strategy_used=MatchStrategy.EXACT,
        )

    def _apply_full_file(self, original: str, diff_text: str, dry_run: bool) -> ApplyResult:
        """Apply full file replacement."""
        # Extract code from markdown block if present
        if diff_text.strip().startswith("```"):
            # Remove markdown fence
            lines = diff_text.strip().split("\n")
            if lines[0].startswith("```") and lines[-1].strip() == "```":
                new_content = "\n".join(lines[1:-1])
            else:
                new_content = diff_text
        else:
            new_content = diff_text
        
        return ApplyResult(
            success=True,
            patched_content=new_content if not dry_run else original,
            original_content=original,
            hunks_applied=1,
            details=["✓ Replaced entire file content"],
            strategy_used=MatchStrategy.EXACT,
        )


# Singleton instance
_diff_applier: Optional[DiffApplier] = None


def get_diff_applier(fuzzy_threshold: float = 0.8) -> DiffApplier:
    """Get the singleton diff applier instance."""
    global _diff_applier
    if _diff_applier is None:
        _diff_applier = DiffApplier(fuzzy_threshold=fuzzy_threshold)
    return _diff_applier
