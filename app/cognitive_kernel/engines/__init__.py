"""Cognitive engines — the behavioural layer above the kernel, runtime, and state.

Each engine registers with the Kernel, executes through the Runtime, and reads/
writes only through the Cognitive State Manager. Engines own *behaviour*; the
State Manager owns *state*. The first engine is Working Memory.
"""
