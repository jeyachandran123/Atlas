"""
AST-aware code chunker.

Uses tree-sitter to parse source files into Abstract Syntax Trees,
then extracts semantic units: functions, classes, methods, imports.

WHY AST CHUNKING OVER TEXT CHUNKING:
- Text chunking breaks mid-function, making chunks incomplete and misleading
- AST chunking produces complete semantic units — one function = one chunk
- Retrieval quality improves 30-40% because retrieved chunks are self-contained
- The model receives coherent code it can reason about, not fragments

WHY TREE-SITTER:
- Supports 40+ languages with one consistent API
- Produces concrete syntax trees (handles syntax errors gracefully)
- Much faster than language-specific parsers
- Active community, reliable maintenance
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.indexing.scanner import FileRecord
from app.shared.schemas import ChunkType, CodeChunk

# Maximum tokens per chunk. At ~4 chars/token, 2000 tokens ≈ 8000 chars.
MAX_CHUNK_TOKENS = 2000
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * 4

# Minimum chunk size — avoid indexing tiny one-liner functions
MIN_CHUNK_CHARS = 40

# Lines of overlap when a function must be split (for context continuity)
OVERLAP_LINES = 3


@dataclass
class RawChunk:
    content: str
    chunk_type: ChunkType
    start_line: int
    end_line: int
    function_name: Optional[str] = None
    class_name: Optional[str] = None


class LanguageChunker:
    """
    Base class for language-specific AST chunkers.
    Subclasses implement _extract_chunks using tree-sitter.
    Falls back to line-based chunking if tree-sitter is unavailable.
    """

    language_name: str = "unknown"

    def chunk(self, file_record: FileRecord, content: str) -> list[CodeChunk]:
        """Main entry point. Returns CodeChunks ready for embedding."""
        try:
            raw_chunks = self._extract_chunks(content)
        except Exception:
            # Graceful fallback: line-based chunking
            raw_chunks = self._fallback_chunks(content)

        chunks = []
        for raw in raw_chunks:
            # Split oversized chunks
            sub_chunks = self._split_if_oversized(raw)
            for sub in sub_chunks:
                if len(sub.content.strip()) < MIN_CHUNK_CHARS:
                    continue
                chunks.append(
                    CodeChunk(
                        content=sub.content,
                        file_path=file_record.relative_path,
                        language=file_record.language,
                        chunk_type=sub.chunk_type,
                        start_line=sub.start_line,
                        end_line=sub.end_line,
                        function_name=sub.function_name,
                        class_name=sub.class_name,
                        repo_id="",  # Set by indexer
                        file_hash=file_record.file_hash,
                    )
                )
        return chunks

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        """Override in subclasses for language-specific AST parsing."""
        return self._fallback_chunks(content)

    def _fallback_chunks(self, content: str) -> list[RawChunk]:
        """
        Line-based chunking for unsupported languages or parse errors.
        Groups lines into ~500-line chunks.
        """
        lines = content.split("\n")
        chunk_size = 100  # lines per chunk
        chunks = []

        for i in range(0, len(lines), chunk_size):
            chunk_lines = lines[i : i + chunk_size]
            chunks.append(
                RawChunk(
                    content="\n".join(chunk_lines),
                    chunk_type=ChunkType.MODULE,
                    start_line=i + 1,
                    end_line=min(i + chunk_size, len(lines)),
                )
            )
        return chunks

    def _split_if_oversized(self, raw: RawChunk) -> list[RawChunk]:
        """Split a chunk that exceeds MAX_CHUNK_CHARS at logical boundaries."""
        if len(raw.content) <= MAX_CHUNK_CHARS:
            return [raw]

        lines = raw.content.split("\n")
        chunks = []
        current_lines: list[str] = []
        current_start = raw.start_line
        char_count = 0

        for i, line in enumerate(lines):
            current_lines.append(line)
            char_count += len(line) + 1

            if char_count >= MAX_CHUNK_CHARS:
                chunk_content = "\n".join(current_lines)
                chunks.append(
                    RawChunk(
                        content=chunk_content,
                        chunk_type=raw.chunk_type,
                        start_line=current_start,
                        end_line=current_start + len(current_lines) - 1,
                        function_name=raw.function_name,
                        class_name=raw.class_name,
                    )
                )
                # Start next chunk with overlap
                overlap = current_lines[-OVERLAP_LINES:] if len(current_lines) >= OVERLAP_LINES else current_lines
                current_start = current_start + len(current_lines) - len(overlap)
                current_lines = list(overlap)
                char_count = sum(len(l) + 1 for l in overlap)

        if current_lines:
            chunks.append(
                RawChunk(
                    content="\n".join(current_lines),
                    chunk_type=raw.chunk_type,
                    start_line=current_start,
                    end_line=raw.end_line,
                    function_name=raw.function_name,
                    class_name=raw.class_name,
                )
            )

        return chunks


class PythonChunker(LanguageChunker):
    """
    Python AST chunker using tree-sitter-python.
    Extracts: functions, classes, methods, imports, module docstrings.
    """

    language_name = "python"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_python as tspython
            from tree_sitter import Language, Parser

            PY_LANGUAGE = Language(tspython.language())
            parser = Parser(PY_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks, current_class=None)
        return chunks if chunks else self._fallback_chunks(content)

    def _visit_node(self, node, lines: list[str], chunks: list[RawChunk], current_class: Optional[str]) -> None:
        """Recursively visit AST nodes and extract semantic chunks."""
        if node.type == "module":
            # Extract module-level docstring
            for child in node.children:
                if child.type == "expression_statement":
                    inner = child.children[0] if child.children else None
                    if inner and inner.type == "string":
                        start = child.start_point[0]
                        end = child.end_point[0]
                        chunks.append(RawChunk(
                            content="\n".join(lines[start:end + 1]),
                            chunk_type=ChunkType.DOCSTRING,
                            start_line=start + 1,
                            end_line=end + 1,
                        ))
                    break

            # Process top-level imports as one chunk
            import_lines = []
            import_start = None
            for child in node.children:
                if child.type in ("import_statement", "import_from_statement"):
                    if import_start is None:
                        import_start = child.start_point[0]
                    import_lines.append("\n".join(lines[child.start_point[0]:child.end_point[0] + 1]))

            if import_lines and import_start is not None:
                chunks.append(RawChunk(
                    content="\n".join(import_lines),
                    chunk_type=ChunkType.IMPORT,
                    start_line=import_start + 1,
                    end_line=import_start + len(import_lines),
                ))

            for child in node.children:
                self._visit_node(child, lines, chunks, current_class=None)

        elif node.type == "function_definition":
            start = node.start_point[0]
            end = node.end_point[0]
            name = self._get_child_text(node, "identifier", lines)
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.METHOD if current_class else ChunkType.FUNCTION,
                start_line=start + 1,
                end_line=end + 1,
                function_name=name,
                class_name=current_class,
            ))

        elif node.type == "decorated_definition":
            # Handle @decorator-wrapped functions/methods
            for child in node.children:
                if child.type == "function_definition":
                    start = node.start_point[0]  # include decorator in chunk
                    end = node.end_point[0]
                    name = self._get_child_text(child, "identifier", lines)
                    chunks.append(RawChunk(
                        content="\n".join(lines[start:end + 1]),
                        chunk_type=ChunkType.METHOD if current_class else ChunkType.FUNCTION,
                        start_line=start + 1,
                        end_line=end + 1,
                        function_name=name,
                        class_name=current_class,
                    ))
                    break

        elif node.type == "class_definition":
            start = node.start_point[0]
            class_name = self._get_child_text(node, "identifier", lines)

            # Class header (signature + docstring only, not methods)
            body = next((c for c in node.children if c.type == "block"), None)
            if body:
                header_end = body.start_point[0]
                # Include docstring in header
                for child in body.children:
                    if child.type == "expression_statement":
                        inner = child.children[0] if child.children else None
                        if inner and inner.type == "string":
                            header_end = child.end_point[0]
                        break

                chunks.append(RawChunk(
                    content="\n".join(lines[start:header_end + 1]),
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=header_end + 1,
                    class_name=class_name,
                ))

                # Visit methods inside the class
                for child in body.children:
                    self._visit_node(child, lines, chunks, current_class=class_name)

    @staticmethod
    def _get_child_text(node, child_type: str, lines: list[str]) -> Optional[str]:
        for child in node.children:
            if child.type == child_type:
                start_row = child.start_point[0]
                start_col = child.start_point[1]
                end_col = child.end_point[1]
                if start_row < len(lines):
                    line = lines[start_row]
                    extracted = line[start_col:end_col]
                    return extracted if extracted else None
        return None


class GenericChunker(LanguageChunker):
    """
    Regex-based chunker for languages without tree-sitter support yet.
    Handles JavaScript, TypeScript, Java, C#, Go with pattern matching.
    Good enough for V1; replace with proper AST chunkers in V2.
    """

    # Pattern: function/method definitions
    FUNCTION_PATTERNS = {
        "javascript": re.compile(
            r"^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))",
            re.MULTILINE,
        ),
        "typescript": re.compile(
            r"^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>)|(?:public|private|protected|static|\s)+(\w+)\s*\([^)]*\)\s*(?::\s*\S+\s*)?{)",
            re.MULTILINE,
        ),
        "java": re.compile(
            r"^\s*(?:public|private|protected|static|final|abstract|\s)*\s+\w+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\S+\s*)?{",
            re.MULTILINE,
        ),
        "csharp": re.compile(
            r"^\s*(?:public|private|protected|internal|static|virtual|override|abstract|\s)*\s+\w+\s+(\w+)\s*\([^)]*\)\s*{",
            re.MULTILINE,
        ),
        "go": re.compile(
            r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\([^)]*\)",
            re.MULTILINE,
        ),
    }

    def __init__(self, language: str) -> None:
        self.language = language
        self._pattern = self.FUNCTION_PATTERNS.get(language)

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        if not self._pattern:
            return self._fallback_chunks(content)

        lines = content.split("\n")
        matches = list(self._pattern.finditer(content))

        if not matches:
            return self._fallback_chunks(content)

        chunks: list[RawChunk] = []
        for i, match in enumerate(matches):
            start_line = content[: match.start()].count("\n")
            if i + 1 < len(matches):
                end_line = content[: matches[i + 1].start()].count("\n") - 1
            else:
                end_line = len(lines) - 1

            # Extract function name from match groups
            func_name = next((g for g in match.groups() if g), None)
            chunk_content = "\n".join(lines[start_line : end_line + 1])

            chunks.append(
                RawChunk(
                    content=chunk_content,
                    chunk_type=ChunkType.FUNCTION,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                    function_name=func_name,
                )
            )

        return chunks


def get_chunker(language: str) -> LanguageChunker:
    """Factory: return the best available chunker for a language."""
    # Import language-specific chunkers
    try:
        from app.indexing.languages.javascript import JavaScriptChunker, TypeScriptChunker
        from app.indexing.languages.java import JavaChunker
        from app.indexing.languages.go_rust import GoChunker, RustChunker
        from app.indexing.languages.c_cpp import CChunker, CppChunker
        
        chunkers: dict[str, LanguageChunker] = {
            # AST-aware chunkers (tree-sitter)
            "python": PythonChunker(),
            "javascript": JavaScriptChunker(),
            "typescript": TypeScriptChunker(),
            "java": JavaChunker(),
            "go": GoChunker(),
            "rust": RustChunker(),
            "c": CChunker(),
            "cpp": CppChunker(),
            "c++": CppChunker(),
            # Fallback to generic regex-based chunkers
            "csharp": GenericChunker("csharp"),
            "ruby": GenericChunker("ruby"),
            "php": GenericChunker("php"),
        }
    except ImportError:
        # Fallback if tree-sitter packages not available
        chunkers: dict[str, LanguageChunker] = {
            "python": PythonChunker(),
            "javascript": GenericChunker("javascript"),
            "typescript": GenericChunker("typescript"),
            "java": GenericChunker("java"),
            "csharp": GenericChunker("csharp"),
            "go": GenericChunker("go"),
        }
    
    return chunkers.get(language, LanguageChunker())
