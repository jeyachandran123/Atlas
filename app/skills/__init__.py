"""
Skills — reusable instruction packs (SKILL.md) that change HOW Atlas answers.

  parser      SKILL.md frontmatter + validation
  package     .zip / .md extraction with safety limits (nothing is executed)
  installer   install from GitHub / raw https URLs (SSRF-guarded)
  repository  data access, always visibility-scoped
  service     ownership, install state, preferences, built-in seeding
  router      SkillRouter — per-turn selection (explicit /slug, then scoring)
  prompt      renders the "Active skills" system-prompt section
  chat        fail-safe glue used by the chat / workspace paths
"""
