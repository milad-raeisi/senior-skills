# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-18

### Added

- `npx senior-skills@latest update`: brings installed skills up to the newest release and adds new ones. A copy is replaced without a backup only when a manifest (`.senior-skills.json`) proves it is exactly what was installed. Copies that were edited, or whose origin is unknown, are backed up first. Skills from elsewhere that share a name are left alone unless `--force` is given.
- `npx senior-skills list` (the `--list` flag still works).
- 14 CLI tests (`node --test tests/cli.test.mjs`), run in CI on Node 20 and 24.

### Fixed

- Backups no longer go next to the skills as `<name>.bak-<time>`. Agents could load those folders as duplicate skills, and every forced update across six agents created 90 of them. Backups now live in `~/.senior-skills/backups/<time>/`, for both `npx senior-skills` and `install.sh`.

## [1.1.0] - 2026-11-18

### Added

- `npx senior-skills`: a dependency-free Node.js installer published to npm. It detects the coding agents on the machine and installs every skill for each, with `--agent`, `--dir`, `--only`, `--force`, and `--list`. No clone or fork needed.
- CI checks the npm package contents and runs the installer through `npx`.

### Changed

- README quick start now leads with `npx senior-skills`.

## [1.0.0] - 2026-11-17

### Added

- `senior-engineer`: the flagship operating principles and routing table.
- The Senior Five: `state-machine-hunter`, `prior-art-scout`, `bug-triage`, `finish-the-job`, `ci-auditor`.
- `ci-auditor/scripts/ci_audit.py`: splits GitHub Actions job time into queue, setup, and run; read-only, standard library only, with retries for large runs.
- Core craft skills: `systematic-debugging`, `test-driven-development`, `evidence-before-claims`, `plan-before-code`, `staff-review`, `deep-modules`, `security-audit`, `parallel-agents`, `agent-ready-repo`.
- Manifests for Claude Code (plugin and marketplace), Codex, Cursor, and Gemini CLI.
- `scripts/install.sh` for Claude Code, Codex, Cursor, Gemini CLI, Copilot, OpenCode, Windsurf, or any directory.
- `scripts/validate_skills.py`, unit tests, and a CI workflow.
- Copy-paste prompts in `prompts/the-senior-five.md`.
