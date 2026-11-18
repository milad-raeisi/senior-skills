# Contributing to senior-skills

Thanks for helping agents work more like senior engineers. The bar for this repo is simple: **every skill should encode a judgment call that measurably changes what an agent does.** A list of best practices the model already knows doesn't qualify; a decision procedure it gets wrong without help does.

## Good contributions

- **A new skill** for a judgment call agents keep getting wrong. Open a [skill request](../../issues/new?template=skill-request.yml) first so we can discuss scope.
- **Improvements from real use**: a skill that didn't trigger, triggered wrongly, or led an agent astray. Include the prompt and what happened.
- **Better scripts**: deterministic helpers that remove guesswork (like `ci_audit.py`).
- **Ports and packaging** for more agents.

## Writing a skill

```
skills/<name>/
├── SKILL.md          # required: frontmatter + instructions
├── references/       # optional: deep material, loaded only when SKILL.md points to it
└── scripts/          # optional: deterministic helpers, Python standard library only
```

Frontmatter:

```yaml
---
name: my-skill                 # equals the folder name; lowercase and hyphens
description: What it does and when to use it, with concrete trigger phrases. One line, under 1024 characters.
license: MIT
metadata:
  category: craft              # flagship, senior-five, or craft
  version: "1.1.0"             # equals the plugin version
---
```

Guidelines:

1. **The description is the trigger.** Agents decide whether to load a skill from its description alone. Say what it does *and* when to use it, including the phrases users actually type. Lean slightly pushy; under-triggering is the common failure.
2. **Explain why.** Models follow reasons better than capital-letter rules. If you write MUST or NEVER, ask whether a sentence of reasoning would work better.
3. **Stay lean.** Keep `SKILL.md` under 500 lines. Everything in it costs context every time the skill loads; move depth into `references/`.
4. **Give procedures and output formats**, not essays. Phases, checklists, report templates, and tables of "tempting move vs. senior move" work well.
5. **Be safe by default.** Scripts are read-only unless the skill clearly says otherwise. Anything destructive or outward-facing requires the user's approval.
6. **Write original text.** Learn from other skill libraries, credit them in the README, and never copy content without a compatible license and attribution.
7. **Wire it up.** Add the skill to the routing table in `skills/senior-engineer/SKILL.md`, to `README.md`, and to `CHANGELOG.md`.

## Before opening a PR

```bash
python3 scripts/validate_skills.py
python3 -m unittest discover -s tests -v
```

Then try the skill for real: install it with `./scripts/install.sh --link`, give your agent two or three realistic prompts, and compare the result with and without the skill. Mention what you saw in the PR.
