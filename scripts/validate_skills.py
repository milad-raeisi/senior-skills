#!/usr/bin/env python3
"""Validate every skill and manifest in this repository.

Checks that each skills/<name>/SKILL.md has valid frontmatter (name matches the folder,
description within limits and safe for strict YAML parsers), that relative links resolve,
that every skill is routed from senior-engineer and listed in the README, and that all
plugin manifests are valid JSON with the same version. Exits 1 if anything is wrong.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
USE_WHEN_RE = re.compile(r"\buse (when|whenever|for|at|right|before|after)\b", re.IGNORECASE)
CATEGORIES = {"flagship", "senior-five", "craft"}
MAX_NAME, MAX_DESCRIPTION, MAX_BODY_LINES = 64, 1024, 500
MANIFESTS = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".codex-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
    "gemini-extension.json",
]

errors: list[str] = []
warnings: list[str] = []


def error(where: str, message: str) -> None:
    errors.append(f"{where}: {message}")


def warn(where: str, message: str) -> None:
    warnings.append(f"{where}: {message}")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the small YAML subset skills use: `key: value` lines and one level of nesting."""
    if not text.startswith("---\n"):
        raise ValueError("file must start with YAML frontmatter (---)")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter is not closed with ---")
    block, body = text[4:end], text[end + 5:]
    data: dict = {}
    parent = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, sep, value = raw.strip().partition(":")
        if not sep:
            raise ValueError(f"cannot parse frontmatter line: {raw!r}")
        value = value.strip()
        quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
        if quoted:
            value = value[1:-1]
        elif ": " in value or " #" in value:
            raise ValueError(f"unquoted value for {key!r} contains ': ' or ' #', which breaks strict YAML parsers")
        if raw[0] in " \t":
            if parent is None:
                raise ValueError(f"indented line without a parent key: {raw!r}")
            data[parent][key] = value
        elif value == "" and not quoted:
            data[key] = {}
            parent = key
        else:
            data[key] = value
            parent = None
    return data, body


def check_manifests() -> str | None:
    versions: dict[str, str] = {}
    for rel in MANIFESTS:
        path = ROOT / rel
        if not path.exists():
            error(rel, "missing")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            error(rel, f"invalid JSON: {exc}")
            continue
        if data.get("name") != "senior-skills":
            error(rel, f"name should be 'senior-skills', found {data.get('name')!r}")
        if rel.endswith("marketplace.json"):
            plugins = data.get("plugins") or []
            if not plugins:
                error(rel, "no plugins listed")
                continue
            versions[rel] = plugins[0].get("version", "")
            if plugins[0].get("source") != "./":
                error(rel, "plugin source should be './'")
        else:
            versions[rel] = data.get("version", "")
    distinct = set(versions.values())
    if len(distinct) > 1:
        error("manifests", "versions differ: " + ", ".join(f"{k}={v}" for k, v in versions.items()))
    return distinct.pop() if len(distinct) == 1 else None


def check_skill(folder: Path, version: str | None) -> None:
    where = f"skills/{folder.name}/SKILL.md"
    path = folder / "SKILL.md"
    if not path.exists():
        error(f"skills/{folder.name}", "missing SKILL.md")
        return
    text = path.read_text(encoding="utf-8")
    try:
        meta, body = parse_frontmatter(text)
    except ValueError as exc:
        error(where, str(exc))
        return

    name = meta.get("name", "")
    if name != folder.name:
        error(where, f"name {name!r} must equal the folder name {folder.name!r}")
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        error(where, f"name {name!r} must be lowercase words joined by hyphens, at most {MAX_NAME} characters")

    description = meta.get("description", "")
    if not description:
        error(where, "description is required")
    elif len(description) > MAX_DESCRIPTION:
        error(where, f"description is {len(description)} characters; the limit is {MAX_DESCRIPTION}")
    if "<" in description or ">" in description:
        error(where, "description must not contain angle brackets")
    if description and not USE_WHEN_RE.search(description):
        warn(where, "description should say when to use the skill ('Use when ...')")

    if meta.get("license") != "MIT":
        warn(where, "license should be MIT")
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    if metadata.get("category") not in CATEGORIES:
        error(where, f"metadata.category must be one of {sorted(CATEGORIES)}")
    if version and metadata.get("version") != version:
        error(where, f"metadata.version {metadata.get('version')!r} differs from the plugin version {version!r}")

    lines = body.count("\n")
    if lines > MAX_BODY_LINES:
        warn(where, f"body is {lines} lines; move detail into references/ (aim for under {MAX_BODY_LINES})")

    for target in LINK_RE.findall(body):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if not (folder / target.split("#")[0]).exists():
            error(where, f"broken relative link: {target}")


def main() -> int:
    version = check_manifests()
    folders = sorted(p for p in SKILLS.iterdir() if p.is_dir()) if SKILLS.is_dir() else []
    if not folders:
        error("skills", "no skills found")
    for folder in folders:
        check_skill(folder, version)

    router = (SKILLS / "senior-engineer" / "SKILL.md").read_text(encoding="utf-8") if folders else ""
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    for folder in folders:
        if folder.name != "senior-engineer" and f"`{folder.name}`" not in router:
            error("skills/senior-engineer/SKILL.md", f"routing table does not mention `{folder.name}`")
        if f"skills/{folder.name}" not in readme:
            error("README.md", f"does not link skills/{folder.name}")

    for message in warnings:
        print(f"warning  {message}")
    for message in errors:
        print(f"error    {message}")
    status = "FAILED" if errors else "OK"
    print(f"{status}: {len(folders)} skills, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
