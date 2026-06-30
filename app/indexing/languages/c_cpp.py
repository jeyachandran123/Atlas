"""
C/C++ AST chunkers using tree-sitter.

Handles:
- Functions
- Classes (C++ only)
- Methods (C++ only)
- Structs
- Includes
- Namespaces (C++ only)
"""

from __future__ import annotations

from typing import Optional

from app.indexing.chunker import LanguageChunker, RawChunk
from app.shared.schemas import ChunkType


class CChunker(LanguageChunker):
    """
    C AST chunker using tree-sitter-c.
    Extracts functions, structs, includes.
    """

    language_name = "c"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_c as tsc
            from tree_sitter import Language, Parser

            C_LANGUAGE = Language(tsc.language())
            parser = Parser(C_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks)
        return chunks if chunks else self._fallback_chunks(content)

    def _visit_node(self, node, lines: list[str], chunks: list[RawChunk]) -> None:
        """Recursively visit AST nodes and extract semantic chunks."""
        
        # Translation unit (root)
        if node.type == "translation_unit":
            # Extract includes
            include_chunks = self._extract_includes(node, lines)
            chunks.extend(include_chunks)
            
            # Visit declarations
            for child in node.children:
                self._visit_node(child, lines, chunks)

        # Function definitions
        elif node.type == "function_definition":
            start = node.start_point[0]
            end = node.end_point[0]
            func_name = self._get_function_name(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.FUNCTION,
                start_line=start + 1,
                end_line=end + 1,
                function_name=func_name,
            ))

        # Struct declarations
        elif node.type == "struct_specifier":
            start = node.start_point[0]
            end = node.end_point[0]
            struct_name = self._get_struct_name(node, lines)
            
            # Only chunk if it has a name (not anonymous struct)
            if struct_name:
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=end + 1,
                    class_name=struct_name,
                ))

    def _extract_includes(self, root_node, lines: list[str]) -> list[RawChunk]:
        """Extract all #include directives as chunks."""
        include_chunks = []
        
        for child in root_node.children:
            if child.type == "preproc_include":
                start = child.start_point[0]
                end = child.end_point[0]
                
                include_chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.IMPORT,
                    start_line=start + 1,
                    end_line=end + 1,
                ))
        
        return include_chunks

    def _get_function_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract function name from function_definition."""
        declarator = node.child_by_field_name("declarator")
        if declarator:
            # Handle function_declarator
            if declarator.type == "function_declarator":
                declarator = declarator.child_by_field_name("declarator")
            
            # Extract identifier
            if declarator and declarator.type == "identifier":
                return self._get_node_text(declarator, lines)
        
        return None

    def _get_struct_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract struct name."""
        name_node = node.child_by_field_name("name")
        if name_node:
            return self._get_node_text(name_node, lines)
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


class CppChunker(CChunker):
    """
    C++ AST chunker using tree-sitter-cpp.
    Extends C chunker with C++-specific constructs (classes, namespaces).
    """

    language_name = "cpp"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_cpp as tscpp
            from tree_sitter import Language, Parser

            CPP_LANGUAGE = Language(tscpp.language())
            parser = Parser(CPP_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks, current_class=None)
        return chunks if chunks else self._fallback_chunks(content)

    def _visit_node(
        self, node, lines: list[str], chunks: list[RawChunk], current_class: Optional[str] = None
    ) -> None:
        """Recursively visit AST nodes and extract semantic chunks."""
        
        # Translation unit (root)
        if node.type == "translation_unit":
            # Extract includes
            include_chunks = self._extract_includes(node, lines)
            chunks.extend(include_chunks)
            
            # Visit declarations
            for child in node.children:
                self._visit_node(child, lines, chunks, current_class)

        # Class declarations
        elif node.type == "class_specifier":
            start = node.start_point[0]
            class_name = self._get_class_name(node, lines)
            
            # Extract class header (without methods)
            body_node = self._get_child_by_type(node, "field_declaration_list")
            if body_node:
                # Find first method
                first_method_line = None
                for child in body_node.children:
                    if child.type in ("function_definition", "field_declaration"):
                        if self._is_method(child):
                            first_method_line = child.start_point[0]
                            break
                
                if first_method_line:
                    header_end = first_method_line - 1
                else:
                    header_end = body_node.start_point[0] + 2  # Class header only
                
                chunks.append(RawChunk(
                    content="\n".join(lines[start:header_end + 1]),
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=header_end + 1,
                    class_name=class_name,
                ))
                
                # Visit methods
                for child in body_node.children:
                    self._visit_node(child, lines, chunks, class_name)

        # Function definitions
        elif node.type == "function_definition":
            start = node.start_point[0]
            end = node.end_point[0]
            func_name = self._get_function_name(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.METHOD if current_class else ChunkType.FUNCTION,
                start_line=start + 1,
                end_line=end + 1,
                function_name=func_name,
                class_name=current_class,
            ))

        # Namespace declarations
        elif node.type == "namespace_definition":
            # Visit contents of namespace without creating a chunk for namespace itself
            for child in node.children:
                self._visit_node(child, lines, chunks, current_class)

    def _get_class_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract class name."""
        name_node = node.child_by_field_name("name")
        if name_node:
            return self._get_node_text(name_node, lines)
        return None

    def _is_method(self, node) -> bool:
        """Check if a node is a method definition."""
        return node.type == "function_definition"

    def _get_child_by_type(self, node, node_type: str):
        """Get first child with specific type."""
        for child in node.children:
            if child.type == node_type:
                return child
        return None
