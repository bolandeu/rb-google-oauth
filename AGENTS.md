# AGENTS.md

Pointers for agents. Antagor shows the changing state (statuses, branches, tasks): `antagor board`.

- What the package is, its layout and its invariants: `CLAUDE.md`. Usage: `README.md`.
- Antagor keeps the tasks and epics: `.agents/antagor/`.
- The package Standard: https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md (sections by name, for example «Install»).
- The gate before a commit: the `rb-release check` step of `.gitea/workflows/ci.yml` — run that command.

## Particular to this package

- A library, not a CLI: no console script, so the gate skips `standard: commands|json|errors|health` (Standard, Technology). `[tool.rb.install]`: `homeserver = []`, `mac = false`. Tools take it as a git-tag or registry dependency.
- The help of `auth` commands is a contract: change a docstring, then `uv run pytest --snapshot-update` and read the diff in `tests/snapshots/help/`.
- Recommended rules not followed: `requires-python` is `>=3.11` (the consumers still run on it); the code and messages are partly in Russian.
