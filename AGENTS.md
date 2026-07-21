# Agent Guidelines

## User Stories

Before implementing tracker features or changing tracker behavior, read [USER_STORIES.md](USER_STORIES.md) and compare it with:

- the current code paths you are about to touch
- the new requirements from the user or issue
- any tests that describe the same behavior

If the code, requirements, and user stories disagree, resolve the behavior deliberately instead of preserving stale documentation. Update [USER_STORIES.md](USER_STORIES.md) in the same change whenever tracker behavior changes.

## General Workflow

- follow the rules described in files in .local_agent_instructions. 
  they are meant for developers who need to add some clarifications, overrides regarding
  their work stations
- Prefer the existing Django, Ninja, Alpine.js, and Celery patterns used in this repository.
- Keep documentation claims tied to code that exists in the current tree.
- Do not treat generated or derived tracker sessions as source-of-truth data; tracker events are the source of truth and reconciliation derives sessions.
- Before running tests, manually start the Docker services with `docker compose up -d` or foreground `docker compose up` in the repository root. This manual prerequisite is intentional; test setup must not build, start, stop, or otherwise spawn Docker containers.
- Before marking a task as done, make sure tests, type checks and linters pass. The general README.md contains instructions for running these checks.
- follow the rules described in [engineering-standards.md](engineering-standards.md)
- For any test work (adding, deleting, or auditing tests), follow [QA.md](QA.md) — it is binding and records the test philosophy, how to run the unit and end-to-end suites, and settled QA decisions.

