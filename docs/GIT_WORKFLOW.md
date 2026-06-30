# Git Workflow Guide

## Branch Strategy

### Main Branches
- **`main`**: Production-ready code, always stable
- **`dev`**: Integration branch for features, tested before merging to main

### Feature Branches
Create feature branches for all new work:
```bash
# From dev
git checkout dev
git pull origin dev

# Create feature branch
git checkout -b feature/my-feature-name
# OR for fixes
git checkout -b fix/bug-description
```

## Workflow

### 1. Work on Feature Branch
```bash
# Make changes
git add .
git commit -m "feat: add new feature"

# Keep commits small and focused
git commit -m "feat: add user authentication"
git commit -m "test: add auth unit tests"
git commit -m "docs: update auth documentation"
```

### 2. Push and Create PR
```bash
# Push feature branch
git push origin feature/my-feature-name

# Create PR on GitHub: feature/my-feature-name -> dev
# CI will run automatically (ruff, black, mypy, pytest)
```

### 3. Review and Merge
- Wait for CI to pass (green checkmark)
- Review code changes
- Merge PR to `dev`
- Delete feature branch

### 4. Release to Main
When `dev` is stable and ready for release:
```bash
# Create release PR: dev -> main
# CI runs again
# After approval, merge to main
# Tag the release
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
```

## Commit Message Convention

Follow conventional commits format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types:
- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Formatting, missing semicolons, etc.
- **refactor**: Code restructuring without behavior change
- **test**: Adding or updating tests
- **chore**: Build, CI, dependencies

### Examples:
```bash
git commit -m "feat(agents): add review agent with adversarial validation"
git commit -m "fix(tool-planner): improve JSON parsing robustness"
git commit -m "docs: update README with V1.2 architecture"
git commit -m "test(memory): add long-term memory integration tests"
git commit -m "chore: migrate from MSSQL to PostgreSQL"
```

## PR Guidelines

### Before Creating PR:
- [ ] All tests pass locally
- [ ] Code follows style guide (ruff, black)
- [ ] Type hints added (mypy passes)
- [ ] Documentation updated
- [ ] Commit messages follow convention

### PR Description Template:
```markdown
## What
Brief description of changes

## Why
Motivation and context

## How
Implementation approach

## Testing
How was this tested?

## Checklist
- [ ] Tests pass
- [ ] Docs updated
- [ ] Breaking changes documented
```

## Useful Commands

```bash
# Check current branch
git branch

# See what changed
git status
git diff

# Undo uncommitted changes
git checkout -- <file>

# Amend last commit
git commit --amend

# Rebase on dev (keep history clean)
git checkout feature/my-feature
git rebase dev

# Interactive rebase (squash commits)
git rebase -i HEAD~3

# Cherry-pick a commit
git cherry-pick <commit-hash>

# Stash work in progress
git stash
git stash pop
```

## CI Integration

Every push and PR triggers:
1. **Ruff** - Linting
2. **Black** - Formatting check
3. **MyPy** - Type checking
4. **Pytest** - Tests with 75% coverage requirement

Fix issues before merging:
```bash
# Run locally first
ruff check app tests
black --check app tests
mypy app --ignore-missing-imports
pytest --cov=app --cov-fail-under=75
```

## Emergency Hotfix

For critical production bugs:
```bash
# Branch from main
git checkout main
git checkout -b hotfix/critical-bug

# Fix and test
git commit -m "fix: critical security issue"

# PR directly to main
# After merge, also merge main -> dev
```

## Best Practices

1. **Small PRs**: Easier to review, less likely to break things
2. **Descriptive commits**: Future you will thank you
3. **Test before pushing**: Don't rely on CI to catch basic issues
4. **Rebase, don't merge**: Keep history linear and clean
5. **Delete merged branches**: Reduce clutter
6. **Review your own PR**: Catch mistakes before others do

## Current Status

**As of P2 completion**:
- ✅ CI pipeline active (.github/workflows/ci.yml)
- ✅ Main branch stable
- ✅ Feature branch workflow documented
- 🔄 Recommended: Create `dev` branch for integration

```bash
# Create dev branch (one-time setup)
git checkout -b dev
git push -u origin dev

# Set dev as default branch in GitHub settings
```

---

**Follow this workflow going forward for all changes, including API development.**
