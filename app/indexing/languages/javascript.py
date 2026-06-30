"""
JavaScript/TypeScript AST chunker using tree-sitter.

Handles:
- Functions (regular, arrow, async)
- Classes (ES6+ classes with methods)
- Exports (named, default, re-exports)
- Imports (ES6, CommonJS require)
- TypeScript interfaces, types, enums
"""

from __future__ import annotations

from typing import Optional

from app.indexing.chunker import LanguageChunker, RawChunk
from app.shared.schemas import ChunkType


class JavaScriptChunker(LanguageChunker):
    """
    JavaScript AST chunker using tree-sitter-javascript.
    Extracts functions, classes, methods, imports, exports.
    """

    language_name = "javascript"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_javascript as tsjs
            from tree_sitter import Language, Parser

            JS_LANGUAGE = Language(tsjs.language())
            parser = Parser(JS_LANGUAGE)
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
        
        # Program (root) or block - visit children
        if node.type in ("program", "statement_block", "export_statement"):
            # Collect all imports at module level
            if node.type == "program":
                import_chunks = self._extract_imports(node, lines)
                chunks.extend(import_chunks)
            
            for child in node.children:
                self._visit_node(child, lines, chunks, current_class)

        # Function declarations
        elif node.type == "function_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            name = self._get_function_name(node, lines)
            
            chunks.append(RawChunk(
                content="\n".join(lines[start:end + 1]),
                chunk_type=ChunkType.FUNCTION,
                start_line=start + 1,
                end_line=end + 1,
                function_name=name,
                class_name=current_class,
            ))

        # Arrow functions assigned to variables
        elif node.type == "lexical_declaration" or node.type == "variable_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    # Check if value is arrow function or function expression
                    value_node = self._get_child_by_field(child, "value")
                    if value_node and value_node.type in ("arrow_function", "function"):
                        start = node.start_point[0]
                        end = node.end_point[0]
                        name_node = self._get_child_by_field(child, "name")
                        name = self._get_node_text(name_node, lines) if name_node else None
                        
                        chunks.append(RawChunk(
                            content="\n".join(lines[start:end + 1]),
                            chunk_type=ChunkType.FUNCTION,
                            start_line=start + 1,
                            end_line=end + 1,
                            function_name=name,
                            class_name=current_class,
                        ))

        # Class declarations
        elif node.type == "class_declaration":
            start = node.start_point[0]
            end = node.end_point[0]
            class_name = self._get_class_name(node, lines)
            
            # Extract class header (without methods)
            body_node = self._get_child_by_type(node, "class_body")
            if body_node and body_node.children:
                # Class header up to first method
                first_method_line = body_node.start_point[0] + 1
                header_content = "\n".join(lines[start:first_method_line + 1])
                
                chunks.append(RawChunk(
                    content=header_content,
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=first_method_line + 1,
                    class_name=class_name,
                ))
                
                # Extract methods
                for child in body_node.children:
                    if child.type in ("method_definition", "field_definition"):
                        method_start = child.start_point[0]
                        method_end = child.end_point[0]
                        method_name = self._get_method_name(child, lines)
                        
                        chunks.append(RawChunk(
                            content="\n".join(lines[method_start:method_end + 1]),
                            chunk_type=ChunkType.METHOD,
                            start_line=method_start + 1,
                            end_line=method_end + 1,
                            function_name=method_name,
                            class_name=class_name,
                        ))
            else:
                # No methods, just class definition
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.CLASS,
                    start_line=start + 1,
                    end_line=end + 1,
                    class_name=class_name,
                ))

        # Export declarations (export { ... }, export default ...)
        elif node.type == "export_statement":
            # Check if it's exporting a function/class directly
            declaration = self._get_child_by_field(node, "declaration")
            if declaration and declaration.type in ("function_declaration", "class_declaration"):
                self._visit_node(declaration, lines, chunks, current_class)

    def _extract_imports(self, program_node, lines: list[str]) -> list[RawChunk]:
        """Extract all import statements as a single chunk."""
        import_lines = []
        import_start = None
        import_end = None
        
        for child in program_node.children:
            if child.type == "import_statement":
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

    def _get_function_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract function name from function_declaration node."""
        name_node = self._get_child_by_field(node, "name")
        if name_node:
            return self._get_node_text(name_node, lines)
        return None

    def _get_class_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract class name from class_declaration node."""
        name_node = self._get_child_by_field(node, "name")
        if name_node:
            return self._get_node_text(name_node, lines)
        return None

    def _get_method_name(self, node, lines: list[str]) -> Optional[str]:
        """Extract method name from method_definition node."""
        name_node = self._get_child_by_field(node, "name")
        if name_node:
            return self._get_node_text(name_node, lines)
        return None

    def _get_child_by_field(self, node, field_name: str):
        """Get child node by field name."""
        return node.child_by_field_name(field_name)

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
            # Multi-line node (rare for identifiers)
            first_line = lines[start_row][start_col:]
            last_line = lines[end_row][:end_col]
            middle_lines = lines[start_row + 1:end_row]
            return "\n".join([first_line] + middle_lines + [last_line])


class TypeScriptChunker(JavaScriptChunker):
    """
    TypeScript AST chunker using tree-sitter-typescript.
    Extends JavaScript chunker with TypeScript-specific constructs.
    """

    language_name = "typescript"

    def _extract_chunks(self, content: str) -> list[RawChunk]:
        try:
            import tree_sitter_typescript as tsts
            from tree_sitter import Language, Parser

            TS_LANGUAGE = Language(tsts.language_typescript())
            parser = Parser(TS_LANGUAGE)
        except ImportError:
            return self._fallback_chunks(content)

        tree = parser.parse(content.encode("utf-8"))
        lines = content.split("\n")
        chunks: list[RawChunk] = []

        self._visit_node(tree.root_node, lines, chunks, current_class=None)
        
        # Also extract TypeScript-specific constructs
        self._extract_typescript_specific(tree.root_node, lines, chunks)
        
        return chunks if chunks else self._fallback_chunks(content)

    def _extract_typescript_specific(self, node, lines: list[str], chunks: list[RawChunk]) -> None:
        """Extract TypeScript interfaces, types, and enums."""
        for child in node.children:
            # Interface declarations
            if child.type == "interface_declaration":
                start = child.start_point[0]
                end = child.end_point[0]
                name_node = self._get_child_by_field(child, "name")
                name = self._get_node_text(name_node, lines) if name_node else None
                
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.CLASS,  # Treat interface like class
                    start_line=start + 1,
                    end_line=end + 1,
                    class_name=name,
                ))

            # Type alias declarations
            elif child.type == "type_alias_declaration":
                start = child.start_point[0]
                end = child.end_point[0]
                name_node = self._get_child_by_field(child, "name")
                name = self._get_node_text(name_node, lines) if name_node else None
                
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.CLASS,  # Treat type alias like class
                    start_line=start + 1,
                    end_line=end + 1,
                    class_name=name,
                ))

            # Enum declarations
            elif child.type == "enum_declaration":
                start = child.start_point[0]
                end = child.end_point[0]
                name_node = self._get_child_by_field(child, "name")
                name = self._get_node_text(name_node, lines) if name_node else None
                
                chunks.append(RawChunk(
                    content="\n".join(lines[start:end + 1]),
                    chunk_type=ChunkType.CLASS,  # Treat enum like class
                    start_line=start + 1,
                    end_line=end + 1,
                    class_name=name,
                ))
