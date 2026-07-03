"""
Language-specific prompt modules.
"""

from __future__ import annotations

TYPESCRIPT = """\
TypeScript expertise: strict mode, utility types (Partial, Required, Pick, \
Omit, Record, Exclude, Extract), generics, conditional types, mapped types, \
template literal types, discriminated unions, and declaration merging. \
No `any`. Explicit return types on all public functions."""

JAVASCRIPT = """\
JavaScript expertise: ES2024+ features, async/await, Promises, generators, \
WeakMap/WeakSet, Proxy/Reflect, module patterns, \
and V8 optimization techniques."""

PYTHON = """\
Python expertise: type hints (PEP 484/526/612), dataclasses, Pydantic, \
async/await with asyncio, context managers, generators, \
decorators, and Python 3.12+ features. Follow PEP 8."""

CSHARP = """\
C# expertise: async/await, LINQ, records, pattern matching, \
nullable reference types, source generators, \
and .NET 8+ features. Follow Microsoft coding conventions."""

JAVA = """\
Java expertise: Java 21+ features (records, sealed classes, pattern matching, \
virtual threads), Stream API, Optional, CompletableFuture, \
and Spring ecosystem integration."""

KOTLIN = """\
Kotlin expertise: coroutines, Flow, sealed classes, data classes, \
extension functions, DSL builders, and Kotlin Multiplatform."""

GO = """\
Go expertise: goroutines, channels, context propagation, interfaces, \
error wrapping (fmt.Errorf with %w), table-driven tests, \
and idiomatic Go patterns (no OOP inheritance)."""

RUST = """\
Rust expertise: ownership, borrowing, lifetimes, traits, generics, \
async with Tokio, error handling with thiserror/anyhow, \
and zero-cost abstractions."""

PHP = """\
PHP expertise: PHP 8.3+ features (fibers, enums, readonly properties, \
named arguments), Composer, PSR standards, \
and modern PHP patterns (no global state)."""

SWIFT = """\
Swift expertise: Swift concurrency (async/await, actors), \
Combine framework, SwiftUI, Codable, \
and Swift Package Manager."""

DART = """\
Dart expertise: null safety, async/await, streams, \
isolates, and Flutter widget patterns."""
