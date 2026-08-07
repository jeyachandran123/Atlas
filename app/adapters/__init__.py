"""Infrastructure adapters — the outside edge of the hexagon.

Modules here implement ports declared by the platform packages and are bound to
them by a composition root (an API dependency, a worker's startup). The
dependency arrow runs one way: an adapter imports the port it implements, and no
platform package ever imports an adapter.
"""
