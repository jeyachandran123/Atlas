"""Unit tests for the AST-aware code chunker."""

from __future__ import annotations

import pytest

from app.indexing.chunker import GenericChunker, PythonChunker, get_chunker
from app.indexing.scanner import FileRecord
from app.shared.schemas import ChunkType


def _make_file_record(content: str, language: str = "python", path: str = "test.py") -> FileRecord:
    return FileRecord(
        path=f"/repo/{path}",
        relative_path=path,
        language=language,
        file_hash="abc123",
        size_bytes=len(content.encode()),
        is_new=True,
    )


PYTHON_CODE = '''"""Module docstring."""

import os
import sys
from typing import Optional


CONSTANT = 42


class MyService:
    """A service class."""

    def __init__(self, name: str) -> None:
        self.name = name

    def process(self, data: dict) -> Optional[str]:
        """Process some data."""
        if not data:
            return None
        return str(data)

    @staticmethod
    def validate(value: str) -> bool:
        return bool(value)


def standalone_function(x: int, y: int) -> int:
    """A standalone function."""
    return x + y
'''


def test_python_chunker_finds_class():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)

    class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS]
    assert len(class_chunks) >= 1
    assert any(c.class_name == "MyService" for c in class_chunks)


def test_python_chunker_finds_methods():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)

    method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
    method_names = [c.function_name for c in method_chunks]
    assert "__init__" in method_names
    assert "process" in method_names
    assert "validate" in method_names


def test_python_chunker_finds_standalone_function():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)

    func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
    assert any(c.function_name == "standalone_function" for c in func_chunks)


def test_python_chunker_includes_file_path():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE, path="src/service.py")
    chunks = chunker.chunk(record, PYTHON_CODE)
    assert all(c.file_path == "src/service.py" for c in chunks)


def test_python_chunker_line_numbers():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)
    for chunk in chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line


def test_chunker_falls_back_for_unknown_language():
    chunker = get_chunker("unknown_lang")
    record = FileRecord(
        path="/repo/test.xyz",
        relative_path="test.xyz",
        language="unknown_lang",
        file_hash="abc",
        size_bytes=100,
        is_new=True,
    )
    content = "\n".join(f"line {i}" for i in range(200))
    chunks = chunker.chunk(record, content)
    assert len(chunks) > 0  # fallback produces chunks


def test_get_chunker_returns_python_chunker():
    chunker = get_chunker("python")
    assert isinstance(chunker, PythonChunker)


def test_get_chunker_returns_javascript_chunker():
    """Test that JavaScript now gets AST chunker instead of generic."""
    from app.indexing.languages.javascript import JavaScriptChunker
    
    chunker = get_chunker("javascript")
    # Should now return JavaScriptChunker, not GenericChunker
    assert isinstance(chunker, JavaScriptChunker)


def test_chunker_skips_empty_content():
    chunker = PythonChunker()
    record = _make_file_record("   \n  \n  ")
    chunks = chunker.chunk(record, "   \n  \n  ")
    # Empty/whitespace-only content should produce no meaningful chunks
    assert all(len(c.content.strip()) >= 40 for c in chunks)


def test_chunker_splits_oversized_function():
    """Functions larger than MAX_CHUNK_CHARS should be split."""
    large_func = "def large_function():\n" + "\n".join(
        f"    x_{i} = {i}  # some computation" for i in range(1000)
    )
    chunker = PythonChunker()
    record = _make_file_record(large_func)
    chunks = chunker.chunk(record, large_func)

    for chunk in chunks:
        assert len(chunk.content) <= 8100  # MAX_CHUNK_CHARS * 1.01 tolerance


def test_javascript_chunker():
    js_code = """
function authenticate(user, password) {
    if (!user || !password) return false;
    return checkCredentials(user, password);
}

const validateToken = async (token) => {
    const payload = await decodeJWT(token);
    return payload.exp > Date.now();
};
"""
    chunker = GenericChunker("javascript")
    record = _make_file_record(js_code, language="javascript", path="auth.js")
    chunks = chunker.chunk(record, js_code)
    assert len(chunks) > 0



# Tests for new language chunkers

def test_typescript_chunker():
    """Test TypeScript AST chunker extracts interfaces and types."""
    ts_code = """
interface User {
    name: string;
    age: number;
}

type Status = 'active' | 'inactive';

class UserService {
    getUser(id: string): User {
        return { name: 'Test', age: 30 };
    }
}
"""
    try:
        from app.indexing.languages.javascript import TypeScriptChunker
        chunker = TypeScriptChunker()
        record = _make_file_record(ts_code, language="typescript", path="user.ts")
        chunks = chunker.chunk(record, ts_code)
        
        # Should find interface, type, class, and method
        assert len(chunks) > 0
        class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS]
        assert len(class_chunks) >= 2  # interface + class (or type)
    except ImportError:
        pytest.skip("tree-sitter-typescript not installed")


def test_java_chunker():
    """Test Java AST chunker extracts classes and methods."""
    java_code = """package com.example;

import java.util.List;
import java.util.ArrayList;

public class UserService {
    private String serviceName;
    
    public UserService() {
        this.serviceName = "UserService";
        System.out.println("Service initialized");
    }
    
    public String getName() {
        return serviceName;
    }
    
    public static void main(String[] args) {
        UserService service = new UserService();
        System.out.println(service.getName());
    }
}
"""
    try:
        from app.indexing.languages.java import JavaChunker
        chunker = JavaChunker()
        record = _make_file_record(java_code, language="java", path="UserService.java")
        chunks = chunker.chunk(record, java_code)
        
        # Should find class and methods
        assert len(chunks) > 0
        
        method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
        assert len(method_chunks) >= 2  # constructor + methods
    except ImportError:
        pytest.skip("tree-sitter-java not installed")


def test_go_chunker():
    """Test Go AST chunker extracts functions and methods."""
    go_code = """
package main

import "fmt"

type User struct {
    Name string
    Age  int
}

func (u *User) GetName() string {
    return u.Name
}

func NewUser(name string) *User {
    return &User{Name: name}
}

func main() {
    fmt.Println("Hello")
}
"""
    try:
        from app.indexing.languages.go_rust import GoChunker
        chunker = GoChunker()
        record = _make_file_record(go_code, language="go", path="main.go")
        chunks = chunker.chunk(record, go_code)
        
        # Should find package, imports, struct, method, functions
        assert len(chunks) > 0
        func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
        assert len(func_chunks) >= 2  # NewUser + main
        
        method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
        assert len(method_chunks) >= 1  # GetName
    except ImportError:
        pytest.skip("tree-sitter-go not installed")


def test_rust_chunker():
    """Test Rust AST chunker extracts structs, traits, and impl blocks."""
    rust_code = """use std::fmt;
use std::collections::HashMap;

struct User {
    name: String,
    age: u32,
    email: String,
}

impl User {
    fn new(name: String) -> Self {
        User { 
            name, 
            age: 0,
            email: String::new()
        }
    }
    
    fn get_name(&self) -> &str {
        &self.name
    }
    
    fn set_age(&mut self, age: u32) {
        self.age = age;
    }
}

fn main() {
    let user = User::new(String::from("Alice"));
    println!("User: {}", user.get_name());
}
"""
    try:
        from app.indexing.languages.go_rust import RustChunker
        chunker = RustChunker()
        record = _make_file_record(rust_code, language="rust", path="main.rs")
        chunks = chunker.chunk(record, rust_code)
        
        # Should find struct, impl, methods, function
        assert len(chunks) > 0
        
        # At least some chunks should be extracted
        func_or_method_chunks = [c for c in chunks if c.chunk_type in (ChunkType.FUNCTION, ChunkType.METHOD)]
        assert len(func_or_method_chunks) >= 1  # At least main function
    except ImportError:
        pytest.skip("tree-sitter-rust not installed")


def test_c_chunker():
    """Test C AST chunker extracts functions and structs."""
    c_code = """#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct User {
    char name[50];
    int age;
};

void greet(const char* name) {
    printf("Hello, %s!\\n", name);
    printf("Welcome to our program\\n");
}

int calculate_sum(int a, int b) {
    int result = a + b;
    return result;
}

int main() {
    greet("World");
    int sum = calculate_sum(5, 10);
    printf("Sum: %d\\n", sum);
    return 0;
}
"""
    try:
        from app.indexing.languages.c_cpp import CChunker
        chunker = CChunker()
        record = _make_file_record(c_code, language="c", path="main.c")
        chunks = chunker.chunk(record, c_code)
        
        # Should find functions
        assert len(chunks) > 0
        
        func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
        assert len(func_chunks) >= 1  # At least one function
    except ImportError:
        pytest.skip("tree-sitter-c not installed")


def test_cpp_chunker():
    """Test C++ AST chunker extracts classes and methods."""
    cpp_code = """
#include <iostream>
#include <string>

class User {
private:
    std::string name;
    
public:
    User(std::string n) : name(n) {}
    
    std::string getName() {
        return name;
    }
    
    static void printInfo() {
        std::cout << "User class" << std::endl;
    }
};

int main() {
    User u("Alice");
    std::cout << u.getName() << std::endl;
    return 0;
}
"""
    try:
        from app.indexing.languages.c_cpp import CppChunker
        chunker = CppChunker()
        record = _make_file_record(cpp_code, language="cpp", path="main.cpp")
        chunks = chunker.chunk(record, cpp_code)
        
        # Should find includes, class, methods, functions
        assert len(chunks) > 0
        class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS]
        assert len(class_chunks) >= 1
        
        method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
        assert len(method_chunks) >= 2  # constructor + methods
    except ImportError:
        pytest.skip("tree-sitter-cpp not installed")


def test_language_chunker_fallback():
    """Test that chunkers fall back gracefully when tree-sitter unavailable."""
    # Even if tree-sitter packages aren't installed, should get fallback chunker
    chunker = get_chunker("unknown_language")
    content = "\n".join(f"line {i} with some content here" for i in range(200))
    record = _make_file_record(content, language="unknown")
    chunks = chunker.chunk(record, content)
    
    # Should produce at least one chunk (fallback)
    assert len(chunks) >= 1


def test_javascript_class_extraction():
    """Test JavaScript chunker extracts ES6 classes properly."""
    js_code = """class Calculator {
    constructor() {
        this.result = 0;
        this.history = [];
    }
    
    add(x, y) {
        const sum = x + y;
        this.result = sum;
        return sum;
    }
    
    subtract(x, y) {
        const diff = x - y;
        this.result = diff;
        return diff;
    }
    
    static create() {
        return new Calculator();
    }
}
"""
    try:
        from app.indexing.languages.javascript import JavaScriptChunker
        chunker = JavaScriptChunker()
        record = _make_file_record(js_code, language="javascript", path="calc.js")
        chunks = chunker.chunk(record, js_code)
        
        # Should find class and methods
        assert len(chunks) > 0
        
        method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
        assert len(method_chunks) >= 2  # add + subtract + static create
    except ImportError:
        pytest.skip("tree-sitter-javascript not installed")
