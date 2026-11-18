// Tests for bin/senior-skills.mjs. Each test runs the CLI with a throwaway HOME.
// Run: node --test tests/cli.test.mjs

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, sep } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const CLI = join(ROOT, "bin", "senior-skills.mjs");
const SKILLS = readdirSync(join(ROOT, "skills"))
  .filter((name) => existsSync(join(ROOT, "skills", name, "SKILL.md")))
  .sort();

function makeHome(...agentFolders) {
  const home = mkdtempSync(join(tmpdir(), "senior-skills-test-"));
  for (const folder of agentFolders) mkdirSync(join(home, folder), { recursive: true });
  return home;
}

function run(home, ...args) {
  const result = spawnSync(process.execPath, [CLI, ...args], {
    env: { ...process.env, HOME: home, USERPROFILE: home },
    encoding: "utf8",
  });
  return { code: result.status, out: `${result.stdout}${result.stderr}` };
}

const installed = (dir) => readdirSync(dir).filter((name) => !name.startsWith(".")).sort();
const skillFile = (home, skill) => join(home, ".claude", "skills", skill, "SKILL.md");
const packageFile = (skill) => join(ROOT, "skills", skill, "SKILL.md");

function backups(home) {
  const root = join(home, ".senior-skills", "backups");
  return existsSync(root) ? readdirSync(root).map((stamp) => join(root, stamp)) : [];
}

// Same algorithm as the CLI, used only to fake a manifest written by an older release.
function treeHash(dir, base = dir, hash = createHash("sha256")) {
  const files = [];
  const walk = (d) => {
    for (const entry of readdirSync(d)) {
      if (entry === "__pycache__" || entry.endsWith(".pyc")) continue;
      const full = join(d, entry);
      if (statSync(full).isDirectory()) walk(full);
      else files.push(relative(base, full).split(sep).join("/"));
    }
  };
  walk(dir);
  for (const file of files.sort()) hash.update(file).update("\0").update(readFileSync(join(dir, file))).update("\0");
  return hash.digest("hex");
}

test("install detects agents and installs every skill for each", () => {
  const home = makeHome(".claude", ".cursor");
  const { code, out } = run(home);
  assert.equal(code, 0, out);
  assert.deepEqual(installed(join(home, ".claude", "skills")), SKILLS);
  assert.deepEqual(installed(join(home, ".cursor", "skills")), SKILLS);
  assert.equal(existsSync(join(home, ".gemini", "skills")), false);
  assert.match(out, new RegExp(`${SKILLS.length} added`));
});

test("install falls back to Claude Code when no agent is found", () => {
  const home = makeHome();
  assert.equal(run(home).code, 0);
  assert.deepEqual(installed(join(home, ".claude", "skills")), SKILLS);
});

test("running install or update again reports everything up to date", () => {
  const home = makeHome(".claude");
  run(home);
  assert.match(run(home).out, new RegExp(`${SKILLS.length} up to date`));
  const { out } = run(home, "update");
  assert.match(out, new RegExp(`${SKILLS.length} up to date`));
  assert.match(out, /Everything is up to date/);
  assert.deepEqual(backups(home), []);
});

test("install keeps an edited copy; update replaces it and backs it up outside the skills folder", () => {
  const home = makeHome(".claude");
  run(home);
  appendFileSync(skillFile(home, "bug-triage"), "\nmy local edit\n");

  assert.match(run(home).out, /1 kept/);
  assert.match(readFileSync(skillFile(home, "bug-triage"), "utf8"), /my local edit/);

  const { code, out } = run(home, "update");
  assert.equal(code, 0, out);
  assert.match(out, /1 updated/);
  assert.equal(readFileSync(skillFile(home, "bug-triage"), "utf8"), readFileSync(packageFile("bug-triage"), "utf8"));
  const [backup] = backups(home);
  assert.match(readFileSync(join(backup, "claude", "bug-triage", "SKILL.md"), "utf8"), /my local edit/);
  assert.equal(readdirSync(join(home, ".claude", "skills")).some((name) => name.includes(".bak")), false);
});

test("update replaces an unedited copy from an older release without a backup", () => {
  const home = makeHome(".claude");
  run(home);
  // Pretend an older release installed this content, and the user never touched it.
  appendFileSync(skillFile(home, "ci-auditor"), "\nolder release text\n");
  const manifestPath = join(home, ".claude", "skills", ".senior-skills.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  manifest.skills["ci-auditor"] = treeHash(join(home, ".claude", "skills", "ci-auditor"));
  writeFileSync(manifestPath, JSON.stringify(manifest));

  const { out } = run(home, "update");
  assert.match(out, /1 updated/);
  assert.equal(readFileSync(skillFile(home, "ci-auditor"), "utf8"), readFileSync(packageFile("ci-auditor"), "utf8"));
  assert.deepEqual(backups(home), []);
});

test("update replaces an older release that differs only in its version line, without a backup", () => {
  const home = makeHome(".claude");
  run(home);
  // An install from a release that wrote no manifest (1.1.0 and earlier), at an older version.
  rmSync(join(home, ".claude", "skills", ".senior-skills.json"));
  const file = skillFile(home, "bug-triage");
  writeFileSync(file, readFileSync(file, "utf8").replace(/^(\s+version:).*$/m, '$1 "0.9.0"'));

  const { out } = run(home, "update");
  assert.match(out, /1 updated/);
  assert.equal(readFileSync(file, "utf8"), readFileSync(packageFile("bug-triage"), "utf8"));
  assert.deepEqual(backups(home), []);
});

test("update leaves a same-named skill from elsewhere alone unless --force", () => {
  const home = makeHome(".claude");
  const foreign = "---\nname: staff-review\ndescription: someone else's review skill\n---\n";
  mkdirSync(join(home, ".claude", "skills", "staff-review"), { recursive: true });
  writeFileSync(skillFile(home, "staff-review"), foreign);

  run(home);
  const { out } = run(home, "update");
  assert.match(out, /left alone \(same name, not from senior-skills\): staff-review/);
  assert.equal(readFileSync(skillFile(home, "staff-review"), "utf8"), foreign);

  assert.match(run(home, "update", "--force").out, /1 updated/);
  assert.equal(readFileSync(skillFile(home, "staff-review"), "utf8"), readFileSync(packageFile("staff-review"), "utf8"));
  assert.equal(readFileSync(join(backups(home)[0], "claude", "staff-review", "SKILL.md"), "utf8"), foreign);
});

test("update adds skills missing from an existing install", () => {
  const home = makeHome(".claude");
  run(home);
  rmSync(join(home, ".claude", "skills", "deep-modules"), { recursive: true });
  assert.match(run(home, "update").out, /1 added/);
  assert.ok(existsSync(skillFile(home, "deep-modules")));
});

test("update without an existing install changes nothing", () => {
  const home = makeHome(".claude");
  const { code, out } = run(home, "update");
  assert.equal(code, 0);
  assert.match(out, /No senior-skills installation found/);
  assert.equal(existsSync(join(home, ".claude", "skills")), false);
});

test("update recognises copies installed by other tools or older releases (no manifest)", () => {
  const home = makeHome(".claude");
  run(home);
  rmSync(join(home, ".claude", "skills", ".senior-skills.json"));
  appendFileSync(skillFile(home, "finish-the-job"), "\nold\n");
  const { out } = run(home, "update");
  assert.match(out, /1 updated/);
  assert.equal(backups(home).length, 1, "unknown provenance is backed up, never discarded");
});

test("install --force backs up replaced copies outside the skills folder", () => {
  const home = makeHome(".claude");
  run(home);
  appendFileSync(skillFile(home, "plan-before-code"), "\nedit\n");
  assert.match(run(home, "--force").out, /1 updated/);
  assert.equal(readdirSync(join(home, ".claude", "skills")).some((name) => name.includes(".bak")), false);
  assert.equal(backups(home).length, 1);
});

test("--dir and --only install exactly what was asked", () => {
  const home = makeHome(".claude");
  const dir = join(home, "project", ".agents", "skills");
  assert.equal(run(home, "--dir", dir, "--only", "bug-triage,ci-auditor").code, 0);
  assert.deepEqual(installed(dir), ["bug-triage", "ci-auditor"]);
  assert.equal(existsSync(join(home, ".claude", "skills")), false);
});

test("list shows every skill", () => {
  const home = makeHome();
  for (const args of [["list"], ["--list"]]) {
    const { code, out } = run(home, ...args);
    assert.equal(code, 0);
    for (const skill of SKILLS) assert.match(out, new RegExp(`\\b${skill}\\b`));
  }
});

test("bad input exits with code 2 and changes nothing", () => {
  const home = makeHome(".claude");
  for (const args of [["frobnicate"], ["--agent", "bogus"], ["--only", "nope"], ["--dir"], ["update", "install"]]) {
    const { code, out } = run(home, ...args);
    assert.equal(code, 2, `${args.join(" ")}: ${out}`);
  }
  assert.equal(existsSync(join(home, ".claude", "skills")), false);
});
