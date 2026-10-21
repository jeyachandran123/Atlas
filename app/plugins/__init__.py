"""Plugins: read-only connections to external services (GitHub, Gmail, Google Drive).

A plugin answers questions about the user's own account ("my open pull requests",
"unread emails from Priya", "my latest Drive files") by fetching that data at chat
time and giving it to the model as context. Nothing here writes to an external
service; a plugin that could write would need an approval step first.
"""
