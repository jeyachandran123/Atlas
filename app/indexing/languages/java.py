"""
Java AST chunker using tree-sitter.

Handles:
- Classes (public, private, nested)
- Methods (instance, static, constructors)
- Interfaces
- Enums
- Imports and package declarations
- Annotations
"""

from __future__ import annotations

from typing import Optional

from app.indexing.chunker import LanguageChunker, RawChunk
from app.shared.schemas import ChunkType


class JavaChunker(LanguageChunker):
    """
    Java AST chunker using tree-sitter-java.
    Extracts classes, methods, interfaces, enums, imports.
    """

    language_name = "java"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_java as tsjava
            from tree_sitter import Language, Parser

            JAVA_LANGUAGE = Language(tsjava.language())
            parser = Parser(JAVA_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks, current_class=None)
        return chunks if chunks else self._fallback_chunks(content)

    def _visit_node(
        self, node, lines: list[str], chunks: list[RawChunk], current_class: Optional[str]
    ) -> None:
        """Recursively visit AST nodes and extract semantic chunks."""
        
        # Program root
        if node.type == "program":
            # Extract package declaration
            package_node = self._get_child_by_type(node, "package_declaration")
            if package_node:
                start = package_node.start_point[0]
                end = package_node.end_point[0]
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.IMPORT,
                    start_line=start + 1,
                    end_line=end + 1,
                ))
            
            # Extract all imports as one chunk
            import_chunks = self._extract_imports(node, lines)
            chunks.extend(import_chunks)
            
            # Visit class declarations
            for child in node.children:
                self._visit_node(child, lines, chunks, current_class)

        # Class declarations
        elif node.type == "class_declaration":
            start = node.start_point[0]
            class_name = self._get_identifier(node, lines)
            
            # Extract class header (signature + class-level fields)
            body_node = self._get_child_by_type(node, "class_body")
            if body_node:
                # Find first method
                first_method_line = None
                for child in body_node.children:
                    if child.type in ("method_declaration", "constructor_declaration"):
                        first_method_line = child.start_point[0]
                        break
                
                if first_method_line:
                    header_end = first_method_line - 1
                else:
                    header_end = body_node.end_point[0]
                
                chunks.append(RawChunk(
                    content="\n".join(lines[start:header_end + 1]),
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=header_end + 1,
                    class_name=class_name,
                ))
                
                # Visit methods and nested classes
                for child in body_node.children:
                    self._visit_node(child, lines, chunks, class_name)

        # Method declarations
        elif node.type == "method_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            method_name = self._get_identifier(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.METHOD if current_class else ChunkType.FUNCTION,
                start_line=start + 1,
                end_line=end + 1,
                function_name=method_name,
                class_name=current_class,
            ))

        # Constructor declarations
        elif node.type == "constructor_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.METHOD,
                start_line=start + 1,
                end_line=end + 1,
                function_name="<constructor>",
                class_name=current_class,
            ))

        # Interface declarations
        elif node.type == "interface_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            interface_name = self._get_identifier(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.CLASS,
                start_line=start + 1,
                end_line=end + 1,
                class_name=interface_name,
            ))

        # Enum declarations
        elif node.type == "enum_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            enum_name = self._get_identifier(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.CLASS,
                start_line=start + 1,
                end_line=end + 1,
                class_name=enum_name,
            ))

    def _extract_imports(self, program_node, lines: list[str]) -> list[RawChunk]:
        """Extract all import statements as a single chunk."""
        import_lines = []
        import_start = None
        import_end = None
        
        for child in program_node.children:
            if child.type == "import_declaration":
                start = child.start_point[0]
                end = child.end_point[0]
                
                if import_start is None:
                    import_start = start
                import_end = end
                
                import_lines.append("\n".join(lines[start:end + 1]))
        
        if import_lines and import_start is not None and import_end is not None:
            return [RawChunk(
                content="\n".join(import_lines),
                chunk_type=ChunkType.IMPORT,
                start_line=import_start + 1,
                end_line=import_end + 1,
            )]
        
        return []

    def _get_identifier(self, node, lines: list[str]) -> Optional[str]:
        """Extract identifier (name) from a node."""
        for child in node.children:
            if child.type == "identifier":
                return self._get_node_text(child, lines)
        return None

    def _get_child_by_type(self, node, node_type: str):
        """Get first child with specific type."""
        for child in node.children:
            if child.type == node_type:
                return child
        return None

    def _get_node_text(self, node, lines: list[str]) -> str:
        """Extract text content of a node."""
        start_row = node.start_point[0]
        start_col = node.start_point[1]
        end_row = node.end_point[0]
        end_col = node.end_point[1]
        
        if start_row == end_row:
            return lines[start_row][start_col:end_col]
        else:
            first_line = lines[start_row][start_col:]
            last_line = lines[end_row][:end_col]
            middle_lines = lines[start_row + 1:end_row]
            return "\n".join([first_line] + middle_lines + [last_line])
