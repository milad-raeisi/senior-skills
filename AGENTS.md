# AGENTS.md

senior-skills is a library of Agent Skills (`skills/<name>/SKILL.md`) that give coding agents staff-engineer judgment. It ships as a Claude Code plugin and marketplace, a Codex, Cursor, and Gemini CLI extension, and plain skill folders for any agent.

## Using these skills in this repo

Start with `skills/senior-engineer/SKILL.md`; its routing table says which skill fits which situation.

## Commands

- Validate all skills and manifests: `python3 scripts/validate_skills.py`
- Unit tests: `python3 -m unittest discover -s tests -v`
- CLI tests: `node --test tests/cli.test.mjs`
- Try the CI auditor offline: `python3 skills/ci-auditor/scripts/ci_audit.py --from-raw <file>` (create the file with `--save-raw`)
- Install locally for testing: `./scripts/install.sh --agent claude --link`
- Try the npx installer from the checkout: `node bin/senior-skills.mjs --list` (or `--dir <scratch-dir>` to test an install)

Run the validator and tests before finishing any change.

## Layout

- `skills/<name>/SKILL.md`: one skill per folder; the folder name equals the `name` in frontmatter.
- `skills/<name>/references/`: long material loaded only when the skill points to it.
- `skills/<name>/scripts/`: deterministic helpers; Python standard library only.
- `.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`, `gemini-extension.json`, `package.json`: per-agent manifests and the npm package. Keep their `version` fields equal.
- `bin/senior-skills.mjs`: the `npx senior-skills` installer; Node.js standard library only.
- `prompts/`: copy-paste prompt versions for chat UIs without skill support.

## Conventions for skills

- Frontmatter has `name`, `description`, `license: MIT`, and `metadata` with `category` (`flagship`, `senior-five`, or `craft`) and `version`.
- The description says what the skill does **and** when to use it, with concrete trigger phrases. Keep it under 1024 characters, write it as a single line, and avoid `<`, `>`, and `: ` (they break strict YAML parsers).
- Explain *why* in the body instead of shouting rules. Keep `SKILL.md` under 500 lines; move depth into `references/`.
- Every new skill is added to the routing table in `skills/senior-engineer/SKILL.md` and to `README.md`.
- Write original text. Credit inspirations in `README.md`; never copy content from other repositories without a compatible license and attribution.

## Never

- Change a skill's `name` (it breaks installed users' references) without a major version bump and a CHANGELOG note.
- Add scripts that write to remote services or modify the user's repository without the skill stating it clearly.
