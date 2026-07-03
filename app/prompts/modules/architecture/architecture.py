"""
Architecture pattern prompt modules.
"""

from __future__ import annotations

CLEAN_ARCHITECTURE = """\
Clean Architecture: entities → use cases → interface adapters → frameworks. \
Dependencies point inward only. Business logic has zero framework dependencies. \
Use cases orchestrate entities. Adapters translate between layers."""

DDD = """\
Domain-Driven Design: bounded contexts, aggregates, entities, value objects, \
domain events, repositories, domain services, \
and anti-corruption layers between contexts."""

MICROSERVICES = """\
Microservices: service boundaries aligned to bounded contexts, \
async communication (events/messages), \
API gateway pattern, service discovery, \
distributed tracing, and saga pattern for distributed transactions."""

EVENT_DRIVEN = """\
Event-Driven Architecture: event sourcing, CQRS, \
event schema versioning, idempotent consumers, \
dead letter queues, and eventual consistency handling."""

SOLID = """\
SOLID principles applied:
- SRP: one reason to change per class/module
- OCP: extend via new classes, not modification
- LSP: subtypes must be substitutable for base types
- ISP: small focused interfaces over fat interfaces
- DIP: depend on abstractions, inject concretions"""
