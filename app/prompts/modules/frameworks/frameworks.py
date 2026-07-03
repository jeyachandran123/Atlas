"""
Framework-specific prompt modules — frontend and backend.
Each module adds focused expertise on top of the base persona.
"""

from __future__ import annotations

# ── Frontend Frameworks ───────────────────────────────────────────────────────

REACT = """\
React expertise: hooks (useState, useEffect, useCallback, useMemo, useRef, \
useContext, useReducer), component composition, render optimization, \
React.memo, code splitting, Suspense, Error Boundaries, and React 19 patterns."""

NEXTJS = """\
Next.js expertise: App Router, Server Components, Client Components, \
server actions, streaming SSR, route handlers, middleware, ISR, dynamic \
imports, image optimization, and Vercel deployment patterns."""

VUE = """\
Vue.js expertise: Composition API, reactive refs, computed properties, \
watchers, provide/inject, Pinia state management, Vue Router, and \
performance optimization with v-memo and defineAsyncComponent."""

NUXTJS = """\
Nuxt.js expertise: auto-imports, server routes, Nitro engine, \
useFetch/useAsyncData, Nuxt modules, hybrid rendering (SSR/SSG/SPA), \
and Nuxt 3 composables."""

ANGULAR = """\
Angular expertise: standalone components, signals, dependency injection, \
RxJS observables, NgRx state management, lazy loading, change detection \
strategies (OnPush), and Angular 17+ control flow syntax."""

SVELTE = """\
Svelte/SvelteKit expertise: reactive declarations, stores, actions, \
transitions, SvelteKit routing, load functions, form actions, \
and adapter-based deployment."""

REACT_NATIVE = """\
React Native expertise: Expo, navigation (React Navigation), \
native modules, performance (FlatList, memo, useCallback), \
platform-specific code, and OTA updates."""

FLUTTER = """\
Flutter expertise: widget tree composition, state management (Riverpod/Bloc), \
platform channels, animations, responsive layouts, and pub.dev packages."""

# ── Backend Frameworks ────────────────────────────────────────────────────────

FASTAPI = """\
FastAPI expertise: async route handlers, Pydantic v2 models, dependency \
injection, background tasks, WebSockets, middleware, lifespan events, \
SQLAlchemy async, Alembic migrations, and OpenAPI documentation."""

DJANGO = """\
Django expertise: ORM (select_related, prefetch_related, annotations), \
class-based views, DRF serializers, signals, middleware, \
custom management commands, and Django Channels for WebSockets."""

FLASK = """\
Flask expertise: application factory pattern, blueprints, Flask-SQLAlchemy, \
Flask-Migrate, request context, error handlers, and production WSGI deployment."""

EXPRESS = """\
Express.js expertise: middleware chains, router composition, error handling \
middleware, async/await patterns, rate limiting, helmet security, \
and production clustering."""

NESTJS = """\
NestJS expertise: modules, controllers, providers, guards, interceptors, \
pipes, decorators, TypeORM integration, CQRS pattern, \
and microservices with message brokers."""

ASPNET = """\
ASP.NET Core expertise: minimal APIs, controller-based APIs, middleware \
pipeline, dependency injection, Entity Framework Core, SignalR, \
health checks, and Azure deployment."""

SPRING_BOOT = """\
Spring Boot expertise: Spring MVC, Spring Data JPA, Spring Security, \
dependency injection, AOP, actuator endpoints, \
and reactive programming with WebFlux."""

LARAVEL = """\
Laravel expertise: Eloquent ORM, Artisan commands, queues, events, \
broadcasting, Sanctum/Passport auth, Livewire, \
and Horizon for queue monitoring."""
