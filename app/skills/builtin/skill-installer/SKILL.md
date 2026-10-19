---
name: skill-installer
display_name: Skill Installer
description: Helps the user install an existing skill into Atlas from a GitHub URL, a raw SKILL.md link, or a .zip package. Use when the user wants to install, add or import a skill.
icon: download
version: 1.0.0
triggers: [install a skill, install skill, add a skill, import a skill, skill from github, skill url]
modes: [auto, code, business]
---
# Skill Installer

Help the user install a skill someone else wrote.

## Supported sources
- A GitHub folder: `https://github.com/{owner}/{repo}/tree/{branch}/{path}`
  (the folder must contain a `SKILL.md`; `references/` files come along).
- A single GitHub file:
  `https://github.com/{owner}/{repo}/blob/{branch}/{path}/SKILL.md`
- Any public **https** link to a `SKILL.md` or a `.zip` skill package.
- A file on their computer: a `.zip` package or a single `.md` file.

## Steps
1. If the user gave a URL, check it matches one of the forms above. Point out
   problems (http instead of https, a repository root without a SKILL.md,
   a private repository) before they try.
2. Tell them to open **Customize → Skills → Add → Install from GitHub URL** and
   paste the link, or **Add → Upload** for a local file. If the curated list
   is available there, they can pick a skill from it instead.
3. Explain the limits: package ≤ 2 MB, ≤ 50 text files, SKILL.md ≤ 50 KB,
   `name` must be kebab-case and unique among their skills.
4. Remind them that skills are instructions only — Atlas never runs scripts
   from a skill — and that they should only install skills from sources they
   trust, since a skill changes how Atlas answers.
5. After install, the skill appears under **Installed**; they can invoke it
   with `/skill-name` in the composer.
