---
name: skill-creator
display_name: Skill Creator
description: Guides the user through writing a good SKILL.md for a new Atlas skill and produces the finished file. Use when the user wants to create, write or improve a skill.
icon: wand
version: 1.0.0
triggers: [create a skill, new skill, write a skill, make a skill, skill.md, improve this skill]
modes: [auto, code, business]
---
# Skill Creator

Help the user turn a repeatable task into a reusable Atlas skill.

## Interview (keep it short — ask at most 3 questions at a time)
1. What task should the skill handle, and what does a great result look like?
2. When should it activate? Collect 3–8 trigger phrases users would type.
3. Which chat modes apply: `auto`, `code`, `business`?
4. Are there rules, checklists, output formats or examples it must follow?

Skip questions the user has already answered.

## Writing rules
- `name`: kebab-case, at most 64 characters, unique (e.g. `api-docs-writer`).
- `description`: one or two sentences, at most 1024 characters, saying **what**
  the skill does and **when to use it**. Atlas uses it for automatic selection.
- The body is instructions to the assistant: imperative, specific, ordered.
  Prefer checklists and an explicit output format over vague advice.
- Keep the whole file well under 50 KB. Skills are instructions only — never
  include scripts that expect to be executed.

## Deliver
When you have enough information, output the complete file in one fenced
block tagged `skill-md`, for example:

````skill-md
---
name: example-skill
display_name: Example Skill
description: What it does. Use when the user asks for ...
icon: sparkles
version: 1.0.0
triggers: [phrase one, phrase two]
modes: [auto]
---
# Example Skill
Step-by-step instructions...
````

Then tell the user to save it with the **Save as skill** button under the
block, or via **Customize → Skills → Add → Create skill** (paste the file).
Offer one round of refinement.
