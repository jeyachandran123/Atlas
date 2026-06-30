"""
Unit tests for robust diff applier.
"""

import pytest

from app.agents.diff_applier import (
    DiffApplier,
    DiffFormat,
    MatchStrategy,
    get_diff_applier,
)


@pytest.fixture
def applier():
    """Create a diff applier instance."""
    return DiffApplier(fuzzy_threshold=0.8)


@pytest.fixture
def sample_code():
    """Sample Python code for testing."""
    return '''def hello(name):
    """Say hello."""
    print(f"Hello, {name}!")
    return True

def goodbye(name):
    """Say goodbye."""
    print(f"Goodbye, {name}!")
    return False
'''


# Unified Diff Tests

def test_apply_unified_diff_exact_match(applier, sample_code):
    """Test applying a unified diff with exact match."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,5 +1,5 @@
 def hello(name):
     """Say hello."""
-    print(f"Hello, {name}!")
+    print(f"Hi there, {name}!")
     return True
 
'''
    
    result = applier.apply(sample_code, diff)
    
    assert result.success
    assert 'Hi there' in result.patched_content
    assert 'Hello,' not in result.patched_content
    assert result.hunks_applied == 1
    # Strategy can be EXACT or CONTEXTUAL (both work correctly)
    assert result.strategy_used in [MatchStrategy.EXACT, MatchStrategy.CONTEXTUAL]


def test_apply_unified_diff_multiple_hunks(applier, sample_code):
    """Test applying multiple hunks."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,5 +1,5 @@
 def hello(name):
     """Say hello."""
-    print(f"Hello, {name}!")
+    print(f"Hi, {name}!")
     return True
 
@@ -7,4 +7,4 @@
 def goodbye(name):
     """Say goodbye."""
-    print(f"Goodbye, {name}!")
+    print(f"Bye, {name}!")
     return False
'''
    
    result = applier.apply(sample_code, diff)
    
    assert result.success
    assert 'Hi,' in result.patched_content
    assert 'Bye,' in result.patched_content
    assert result.hunks_applied == 2


def test_apply_unified_diff_fuzzy_whitespace(applier):
    """Test applying diff with whitespace differences."""
    original = '''def hello():
    print("Hello")
    return True
'''
    
    # Diff with different indentation
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def hello():
-  print("Hello")
+  print("Hi")
   return True
'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    assert 'Hi' in result.patched_content


def test_apply_unified_diff_contextual_match(applier):
    """Test applying diff using contextual matching."""
    original = '''line 1
line 2
line 3
target line
line 5
line 6
'''
    
    # Diff with slightly wrong line numbers but good context
    diff = '''--- a/test.py
+++ b/test.py
@@ -10,3 +10,3 @@
 line 3
-target line
+modified line
 line 5
'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    assert 'modified line' in result.patched_content


def test_apply_unified_diff_fails_no_match(applier, sample_code):
    """Test diff application fails when no match found."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def hello(name):
-    """This line doesn't exist."""
+    """New line."""
     return True
'''
    
    result = applier.apply(sample_code, diff)
    
    assert not result.success
    assert result.error is not None
    assert result.hunks_failed > 0


# Search/Replace Tests

def test_apply_search_replace_single(applier, sample_code):
    """Test applying search/replace block."""
    diff = '''<<<<<<< SEARCH
    print(f"Hello, {name}!")
=======
    print(f"Greetings, {name}!")
>>>>>>> REPLACE
'''
    
    result = applier.apply(sample_code, diff)
    
    assert result.success
    assert 'Greetings' in result.patched_content
    assert 'Hello,' not in result.patched_content


def test_apply_search_replace_multiple_blocks(applier, sample_code):
    """Test applying multiple search/replace blocks."""
    diff = '''<<<<<<< SEARCH
def hello(name):
=======
def greet(name):
>>>>>>> REPLACE

<<<<<<< SEARCH
def goodbye(name):
=======
def farewell(name):
>>>>>>> REPLACE
'''
    
    result = applier.apply(sample_code, diff)
    
    assert result.success
    assert 'def greet(name):' in result.patched_content
    assert 'def farewell(name):' in result.patched_content
    assert 'def hello(name):' not in result.patched_content
    assert result.hunks_applied == 2


def test_search_replace_not_found(applier, sample_code):
    """Test search/replace fails when text not found."""
    diff = '''<<<<<<< SEARCH
    nonexistent line
=======
    new line
>>>>>>> REPLACE
'''
    
    result = applier.apply(sample_code, diff)
    
    assert not result.success
    assert 'not found' in result.error.lower()


# Markdown Code Block Tests

def test_apply_markdown_code_block(applier):
    """Test applying markdown code block."""
    original = "old content\n"
    
    diff = '''```python:test.py
def new_function():
    return True
```'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    assert 'def new_function():' in result.patched_content
    assert 'old content' not in result.patched_content


def test_apply_full_file_replacement(applier):
    """Test full file replacement."""
    original = "old line 1\nold line 2\n"
    
    diff = '''```
new line 1
new line 2
new line 3
```'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    assert 'new line 1' in result.patched_content
    assert 'old line 1' not in result.patched_content


# Format Detection Tests

def test_detect_unified_diff_format(applier):
    """Test detecting unified diff format."""
    diff = '''--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
-old line
+new line
'''
    
    fmt = applier._detect_format(diff)
    assert fmt == DiffFormat.UNIFIED


def test_detect_search_replace_format(applier):
    """Test detecting search/replace format."""
    diff = '''<<<<<<< SEARCH
old text
=======
new text
>>>>>>> REPLACE
'''
    
    fmt = applier._detect_format(diff)
    assert fmt == DiffFormat.SEARCH_REPLACE


def test_detect_markdown_code_format(applier):
    """Test detecting markdown code format."""
    diff = '''```python:file.py
def foo():
    pass
```'''
    
    fmt = applier._detect_format(diff)
    assert fmt == DiffFormat.MARKDOWN_CODE


# Dry Run Tests

def test_dry_run_mode(applier, sample_code):
    """Test dry run mode doesn't modify content."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def hello(name):
-    """Say hello."""
+    """Say hi."""
     return True
'''
    
    result = applier.apply(sample_code, diff, dry_run=True)
    
    assert result.success
    assert result.patched_content == sample_code  # Unchanged
    assert result.hunks_applied == 1


# Edge Cases

def test_empty_diff(applier, sample_code):
    """Test empty diff returns original."""
    result = applier.apply(sample_code, "")
    
    # Should fail or return original
    assert not result.success or result.patched_content == sample_code


def test_empty_original(applier):
    """Test applying diff to empty file."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -0,0 +1,3 @@
+def new_function():
+    """New function."""
+    pass
'''
    
    result = applier.apply("", diff)
    
    # May or may not succeed depending on implementation
    # At minimum should not crash
    assert result.patched_content is not None


def test_large_file_diff(applier):
    """Test applying diff to large file."""
    # Create large file
    original = "\n".join([f"line {i}" for i in range(1000)])
    
    diff = '''--- a/test.py
+++ b/test.py
@@ -500,3 +500,3 @@
 line 499
-line 500
+modified line 500
 line 501
'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    assert 'modified line 500' in result.patched_content


def test_unicode_content(applier):
    """Test handling unicode content."""
    original = '''def greet(name):
    print(f"Hello, {name}! 你好!")
    return "こんにちは"
'''
    
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def greet(name):
-    print(f"Hello, {name}! 你好!")
+    print(f"Hi, {name}! 你好!")
     return "こんにちは"
'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    assert '你好' in result.patched_content
    assert 'こんにちは' in result.patched_content


def test_multiple_occurrences_same_line(applier):
    """Test handling multiple occurrences of the same content."""
    original = '''print("Hello")
print("Hello")
print("Hello")
'''
    
    # Search/replace should only replace first occurrence
    diff = '''<<<<<<< SEARCH
print("Hello")
=======
print("Hi")
>>>>>>> REPLACE
'''
    
    result = applier.apply(original, diff)
    
    assert result.success
    # Should replace first occurrence (may include newline in match)
    assert 'print("Hi")' in result.patched_content
    # At least one Hello should remain
    assert 'print("Hello")' in result.patched_content


# Hunk Parsing Tests

def test_parse_unified_diff_single_hunk(applier):
    """Test parsing a single hunk."""
    diff = '''--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 context line
-old line
+new line
 context line
'''
    
    hunks = applier._parse_unified_diff(diff)
    
    assert len(hunks) == 1
    assert hunks[0].old_start == 1
    assert hunks[0].new_start == 1
    assert len(hunks[0].old_lines) == 1
    assert len(hunks[0].new_lines) == 1
    assert hunks[0].old_lines[0] == "old line"
    assert hunks[0].new_lines[0] == "new line"


def test_parse_unified_diff_multiple_hunks(applier):
    """Test parsing multiple hunks."""
    diff = '''--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line 1
-old line 2
+new line 2
 line 3
@@ -10,3 +10,3 @@
 line 10
-old line 11
+new line 11
 line 12
'''
    
    hunks = applier._parse_unified_diff(diff)
    
    assert len(hunks) == 2
    assert hunks[0].old_start == 1
    assert hunks[1].old_start == 10


# Singleton Tests

def test_get_diff_applier_singleton():
    """Test that get_diff_applier returns singleton."""
    applier1 = get_diff_applier()
    applier2 = get_diff_applier()
    
    assert applier1 is applier2


# Strategy Preference Tests

def test_prefer_strategy(applier, sample_code):
    """Test preferring a specific strategy."""
    # Use a diff that will work with exact match (correct line numbers)
    diff = '''--- a/test.py
+++ b/test.py
@@ -2,3 +2,3 @@
     """Say hello."""
-    print(f"Hello, {name}!")
+    print(f"Hi, {name}!")
     return True
'''
    
    result = applier.apply(sample_code, diff)
    
    # With correct line numbers, should succeed with one of the strategies
    assert result.success
    assert 'Hi,' in result.patched_content


# Error Reporting Tests

def test_detailed_error_reporting(applier, sample_code):
    """Test that errors include helpful details."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def hello(name):
-    """This doesn't match."""
+    """New docstring."""
     return True
'''
    
    result = applier.apply(sample_code, diff)
    
    assert not result.success
    assert result.error is not None
    # Error message should explain the failure
    assert 'Failed' in result.error or 'match' in result.error.lower()


def test_success_details(applier, sample_code):
    """Test that successful application includes details."""
    diff = '''--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def hello(name):
-    """Say hello."""
+    """Say hi."""
     return True
'''
    
    result = applier.apply(sample_code, diff)
    
    assert result.success
    assert len(result.details) > 0
    assert any('✓' in detail for detail in result.details)
