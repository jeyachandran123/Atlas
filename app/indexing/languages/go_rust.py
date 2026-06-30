"""
Go AST chunker using tree-sitter.

Handles:
- Functions
- Methods (with receivers)
- Structs
- Interfaces
- Imports and package declarations
"""

from __future__ import annotations

from typing import Optional

from app.indexing.chunker import LanguageChunker, RawChunk
from app.shared.schemas import ChunkType


class GoChunker(LanguageChunker):
    """
    Go AST chunker using tree-sitter-go.
    Extracts functions, methods, structs, interfaces, imports.
    """

    language_name = "go"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_go as tsgo
            from tree_sitter import Language, Parser

            GO_LANGUAGE = Language(tsgo.language())
            parser = Parser(GO_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks)
        return chunks if chunks else self._fallback_chunks(content)

    def _visit_node(self, node, lines: list[str], chunks: list[RawChunk]) -> None:
        """Recursively visit AST nodes and extract semantic chunks."""
        
        # Source file (root)
        if node.type == "source_file":
            # Extract package declaration
            package_node = self._get_child_by_type(node, "package_clause")
            if package_node:
                start = package_node.start_point[0]
                end = package_node.end_point[0]
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.IMPORT,
                    start_line=start + 1,
                    end_line=end + 1,
                ))
            
            # Extract imports
            import_chunks = self._extract_imports(node, lines)
            chunks.extend(import_chunks)
            
            # Visit declarations
            for child in node.children:
                self._visit_node(child, lines, chunks)

        # Function declarations
        elif node.type == "function_declaration":
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

        # Method declarations (functions with receivers)
        elif node.type == "method_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            method_name = self._get_function_name(node, lines)
            receiver_type = self._get_receiver_type(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.METHOD,
                start_line=start + 1,
                end_line=end + 1,
                function_name=method_name,
                class_name=receiver_type,
            ))

        # Type declarations (structs, interfaces)
        elif node.type == "type_declaration":
            for spec in node.children:
                if spec.type == "type_spec":
                    start = spec.start_point[0]
                    end = spec.end_point[0]
                    type_name = self._get_type_name(spec, lines)
                    
                    chunks.append(RawChunk(
                        content="\n".join(lines[start:end + 1]),
                        chunk_type=ChunkType.CLASS,
                        start_line=start + 1,
                        end_line=end + 1,
                        class_name=type_name,
                    ))

    def _extract_imports(self, source_node, lines: list[str]) -> list[RawChunk]:
        """Extract all import declarations as chunks."""
        import_chunks = []
        
        for child in source_node.children:
            if child.type == "import_declaration":
                start = child.start_point[0]
                end = child.end_point[0]
                
                import_chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.IMPORT,
                    start_line=start + 1,
                    end_line=end + 1,
                ))
        
        return import_chunks

    def _get_function_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract function/method name."""
        name_node = node.child_by_field_name("name")
        if name_node:
            return self._get_node_text(name_node, lines)
        return None

    def _get_receiver_type(self, node, lines: list[str]) -> Optional[str]:
        """Extract receiver type from method declaration."""
        receiver_node = node.child_by_field_name("receiver")
        if receiver_node:
            # Find type identifier in receiver
            for child in receiver_node.children:
                if child.type == "parameter_list":
                    for param in child.children:
                        if param.type == "parameter_declaration":
                            type_node = param.child_by_field_name("type")
                            if type_node:
                                return self._get_node_text(type_node, lines)
        return None

    def _get_type_name(self, spec_node, lines: list[str]) -> Optional[str]:
        """Extract type name from type_spec."""
        name_node = spec_node.child_by_field_name("name")
        if name_node:
            return self._get_node_text(name_node, lines)
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


class RustChunker(LanguageChunker):
    """
    Rust AST chunker using tree-sitter-rust.
    Extracts functions, methods, structs, traits, impls, enums.
    """

    language_name = "rust"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_rust as tsrust
            from tree_sitter import Language, Parser

            RUST_LANGUAGE = Language(tsrust.language())
            parser = Parser(RUST_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks, current_impl=None)
        return chunks if chunks else self._fallback_chunks(content)

    def _visit_node(
        self, node, lines: list[str], chunks: list[RawChunk], current_impl: Optional[str]
    ) -> None:
        """Recursively visit AST nodes and extract semantic chunks."""
        
        # Source file (root)
        if node.type == "source_file":
            # Extract use statements (imports)
            import_chunks = self._extract_imports(node, lines)
            chunks.extend(import_chunks)
            
            # Visit declarations
            for child in node.children:
                self._visit_node(child, lines, chunks, current_impl)

        # Function items
        elif node.type == "function_item":
            start = node.start_point[0]
            end = node.end_point[0]
            func_name = self._get_identifier(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.METHOD if current_impl else ChunkType.FUNCTION,
                start_line=start + 1,
                end_line=end + 1,
                function_name=func_name,
                class_name=current_impl,
            ))

        # Struct declarations
        elif node.type == "struct_item":
            start = node.start_point[0]
            end = node.end_point[0]
            struct_name = self._get_identifier(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.CLASS,
                start_line=start + 1,
                end_line=end + 1,
                class_name=struct_name,
            ))

        # Enum declarations
        elif node.type == "enum_item":
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

        # Trait declarations
        elif node.type == "trait_item":
            start = node.start_point[0]
            end = node.end_point[0]
            trait_name = self._get_identifier(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.CLASS,
                start_line=start + 1,
                end_line=end + 1,
                class_name=trait_name,
            ))

        # Impl blocks (method implementations)
        elif node.type == "impl_item":
            # Get the type being implemented
            type_node = node.child_by_field_name("type")
            impl_type = self._get_node_text(type_node, lines) if type_node else None
            
            # Extract impl header (signature without methods)
            declaration_list = self._get_child_by_type(node, "declaration_list")
            if declaration_list:
                header_end = declaration_list.start_point[0]
                start = node.start_point[0]
                
                chunks.append(RawChunk(
                    content="\n".join(lines[start:header_end + 1]),
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=header_end + 1,
                    class_name=impl_type,
                ))
                
                # Visit methods in impl block
                for child in declaration_list.children:
                    self._visit_node(child, lines, chunks, impl_type)

    def _extract_imports(self, source_node, lines: list[str]) -> list[RawChunk]:
        """Extract all use declarations as chunks."""
        import_chunks = []
        
        for child in source_node.children:
            if child.type == "use_declaration":
                start = child.start_point[0]
                end = child.end_point[0]
                
                import_chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.IMPORT,
                    start_line=start + 1,
                    end_line=end + 1,
                ))
        
        return import_chunks

    def _get_identifier(self, node, lines: list[str]) -> Optional[str]:
        """Extract identifier (name) from a node."""
        name_node = node.child_by_field_name("name")
        if name_node:
            return self._get_node_text(name_node, lines)
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
