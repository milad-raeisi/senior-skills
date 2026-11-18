#!/usr/bin/env node
// senior-skills: install and update the senior-skills Agent Skills for your coding agents.
// No dependencies. Nothing is overwritten silently, and backups are kept outside every
// skills folder (~/.senior-skills/backups/) so agents never load them as duplicate skills.
//
//   npx senior-skills                         install for every agent found on this machine
//   npx senior-skills@latest update           update installed copies and add new skills
//   npx senior-skills --agent claude          one agent (repeatable, comma-separated, or "all")
//   npx senior-skills --dir ./.agents/skills  any folder, e.g. project-level skills
//   npx senior-skills --only bug-triage,ci-auditor
//   npx senior-skills list                    show the skills in this package

import { createHash } from "node:crypto";
import { cpSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const PKG_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SKILLS_DIR = join(PKG_ROOT, "skills");
const { version } = JSON.parse(readFileSync(join(PKG_ROOT, "package.json"), "utf8"));

const HOME = homedir();
const BACKUP_ROOT = join(HOME, ".senior-skills", "backups");
const MANIFEST = ".senior-skills.json";
// Every senior-skills SKILL.md declares one of these categories; it's how we recognise our own copies.
const SIGNATURE = /^\s+category:\s*"?(flagship|senior-five|craft)"?\s*$/m;

// `marker` is the folder whose presence means the agent is installed; `dir` is where its skills live.
const AGENTS = {
  claude: { label: "Claude Code", dir: join(HOME, ".claude", "skills"), marker: join(HOME, ".claude") },
  codex: { label: "Codex", dir: join(HOME, ".agents", "skills"), marker: join(HOME, ".codex") },
  cursor: { label: "Cursor", dir: join(HOME, ".cursor", "skills"), marker: join(HOME, ".cursor") },
  gemini: { label: "Gemini CLI", dir: join(HOME, ".gemini", "skills"), marker: join(HOME, ".gemini") },
  copilot: { label: "GitHub Copilot", dir: join(HOME, ".copilot", "skills"), marker: join(HOME, ".copilot") },
  opencode: { label: "OpenCode", dir: join(HOME, ".config", "opencode", "skills"), marker: join(HOME, ".config", "opencode") },
  windsurf: { label: "Windsurf", dir: join(HOME, ".codeium", "windsurf", "skills"), marker: join(HOME, ".codeium", "windsurf") },
};
const COMMANDS = ["install", "update", "list"];

const HELP = `senior-skills ${version}: staff-engineer judgment for coding agents

Usage: npx senior-skills [install | update | list] [options]

Commands:
  install    (default) install the skills for each agent found on this machine,
             or Claude Code if none is found; existing copies are left untouched
  update     update installed senior-skills to this version and add any new ones;
             run it as "npx senior-skills@latest update" to get the newest release
  list       list the skills in this package

Options:
  --agent <name>   ${Object.keys(AGENTS).join(", ")}, or all (repeatable or comma-separated)
  --dir <path>     use any folder, e.g. ./.agents/skills (repeatable)
  --only <a,b>     only these skills
  --force          also replace existing copies that "install" would keep, or same-named
                   skills from elsewhere that "update" would leave alone
  -v, --version    print the version
  -h, --help       show this help

Copies you edited are backed up to ~/.senior-skills/backups/<time>/ before being replaced.

Docs: https://github.com/milad-raeisi/senior-skills`;

class UsageError extends Error {}

function parseArgs(argv) {
  const opts = { command: null, agents: [], dirs: [], only: null, force: false };
  const value = (flag, i) => {
    if (i >= argv.length || argv[i].startsWith("-")) throw new UsageError(`${flag} needs a value`);
    return argv[i];
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") opts.help = true;
    else if (arg === "-v" || arg === "--version") opts.version = true;
    else if (arg === "--list") opts.command = "list";
    else if (arg === "--force") opts.force = true;
    else if (arg === "--agent") opts.agents.push(...value(arg, ++i).split(",").filter(Boolean));
    else if (arg === "--dir") opts.dirs.push(value(arg, ++i));
    else if (arg === "--only") opts.only = value(arg, ++i).split(",").filter(Boolean);
    else if (!arg.startsWith("-") && COMMANDS.includes(arg) && !opts.command) opts.command = arg;
    else throw new UsageError(arg.startsWith("-") ? `unknown option: ${arg}` : `unknown command: ${arg}`);
  }
  opts.command ??= "install";
  return opts;
}

// ---------------------------------------------------------------- skills on disk

function availableSkills() {
  return readdirSync(SKILLS_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(SKILLS_DIR, entry.name, "SKILL.md")))
    .map((entry) => entry.name)
    .sort();
}

function describe(skill) {
  const text = readFileSync(join(SKILLS_DIR, skill, "SKILL.md"), "utf8");
  const match = text.match(/^description:\s*(.+)$/m);
  const sentence = match ? match[1].split(/(?<=\.)\s/)[0] : "";
  return sentence.length > 90 ? `${sentence.slice(0, 87)}...` : sentence;
}

function exists(path) {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

const ignored = (name) => name === "__pycache__" || name.endsWith(".pyc");

function listFiles(dir, base = dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    if (ignored(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) files.push(...listFiles(full, base));
    else files.push(relative(base, full).split(sep).join("/"));
  }
  return files.sort();
}

/**
 * Content hash of a skill folder: paths and bytes, ignoring Python caches. With `ignoreVersion`,
 * the `version:` line in SKILL.md is blanked, so an untouched copy of an older release (where
 * only the version differs) can be recognised even without a manifest.
 */
function treeHash(dir, { ignoreVersion = false } = {}) {
  const hash = createHash("sha256");
  for (const file of listFiles(dir)) {
    let content = readFileSync(join(dir, file));
    if (ignoreVersion && file === "SKILL.md") content = content.toString("utf8").replace(/^(\s+version:).*$/m, "$1");
    hash.update(file).update("\0").update(content).update("\0");
  }
  return hash.digest("hex");
}

/** True when `dir` holds a senior-skills skill named `skill` (any version). */
function isOurs(dir, skill) {
  try {
    const text = readFileSync(join(dir, "SKILL.md"), "utf8");
    return SIGNATURE.test(text) && new RegExp(`^name:\\s*${skill}\\s*$`, "m").test(text);
  } catch {
    return false;
  }
}

function readManifest(dir) {
  try {
    const data = JSON.parse(readFileSync(join(dir, MANIFEST), "utf8"));
    return { version: data.version, skills: data.skills ?? {} };
  } catch {
    return { version: null, skills: {} };
  }
}

function hasInstall(dir, skills) {
  return existsSync(join(dir, MANIFEST)) || skills.some((skill) => isOurs(join(dir, skill), skill));
}

function copySkill(skill, dest) {
  cpSync(join(SKILLS_DIR, skill), dest, { recursive: true, filter: (src) => !ignored(basename(src)) });
}

/** Move `from` to `to`, also across file systems. */
function move(from, to) {
  mkdirSync(dirname(to), { recursive: true });
  try {
    renameSync(from, to);
  } catch (error) {
    if (error.code !== "EXDEV") throw error;
    cpSync(from, to, { recursive: true, verbatimSymlinks: true });
    rmSync(from, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------- install / update

function resolveTargets(opts, all) {
  let names = opts.agents.flatMap((name) => (name === "all" ? Object.keys(AGENTS) : [name]));
  for (const name of names) {
    if (!AGENTS[name]) throw new UsageError(`unknown agent: ${name} (choose from ${Object.keys(AGENTS).join(", ")}, all)`);
  }
  const explicit = names.length > 0 || opts.dirs.length > 0;
  if (!explicit) {
    names = Object.keys(AGENTS).filter((name) => existsSync(AGENTS[name].marker));
    if (opts.command === "update") names = names.filter((name) => hasInstall(AGENTS[name].dir, all));
    else if (names.length === 0) names = ["claude"];
  }
  const targets = [...new Set(names)].map((name) => ({ key: name, label: AGENTS[name].label, dir: AGENTS[name].dir }));
  for (const dir of opts.dirs) {
    const full = resolve(dir);
    targets.push({ key: `dir${full.replace(/[^A-Za-z0-9]+/g, "_")}`, label: dir, dir: full });
  }
  return targets;
}

/**
 * Bring `skills` in `target.dir` to this package's version.
 *   install: add missing skills; keep existing copies unless --force.
 *   update:  add missing skills; replace our copies that differ; keep same-named skills
 *            from elsewhere unless --force.
 * A copy is backed up before it is replaced unless the manifest proves it is exactly what we
 * installed earlier (so nobody's edits are lost and pristine updates leave no clutter).
 */
function apply(skills, target, command, force, stamp) {
  mkdirSync(target.dir, { recursive: true });
  const manifest = readManifest(target.dir);
  const r = { added: [], updated: [], current: [], kept: [], foreign: [], backedUp: [] };

  for (const skill of skills) {
    const dest = join(target.dir, skill);
    const sourceHash = treeHash(join(SKILLS_DIR, skill));
    if (!exists(dest)) {
      copySkill(skill, dest);
      manifest.skills[skill] = sourceHash;
      r.added.push(skill);
      continue;
    }
    const ours = isOurs(dest, skill);
    const destHash = existsSync(join(dest, "SKILL.md")) ? treeHash(dest) : null;
    if (ours && destHash === sourceHash) {
      manifest.skills[skill] = sourceHash;
      r.current.push(skill);
      continue;
    }
    if (!force && command === "install") {
      r.kept.push(skill);
      continue;
    }
    if (!force && !ours) {
      r.foreign.push(skill);
      continue;
    }
    const pristine =
      ours &&
      destHash !== null &&
      (manifest.skills[skill] === destHash ||
        treeHash(dest, { ignoreVersion: true }) === treeHash(join(SKILLS_DIR, skill), { ignoreVersion: true }));
    if (pristine) {
      rmSync(dest, { recursive: true, force: true });
    } else {
      move(dest, join(BACKUP_ROOT, stamp, target.key, skill));
      r.backedUp.push(skill);
    }
    copySkill(skill, dest);
    manifest.skills[skill] = sourceHash;
    r.updated.push(skill);
  }

  manifest.version = version;
  writeFileSync(join(target.dir, MANIFEST), `${JSON.stringify(manifest, null, 2)}\n`);
  return r;
}

function summary(r) {
  const parts = [];
  if (r.added.length) parts.push(`${r.added.length} added`);
  if (r.updated.length) parts.push(`${r.updated.length} updated`);
  if (r.current.length) parts.push(`${r.current.length} up to date`);
  if (r.kept.length) parts.push(`${r.kept.length} kept`);
  if (r.foreign.length) parts.push(`${r.foreign.length} left alone`);
  return parts.join(", ") || "nothing to do";
}

function tildify(path) {
  return path.startsWith(HOME) ? `~${path.slice(HOME.length)}` : path;
}

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) return console.log(HELP);
  if (opts.version) return console.log(version);

  const all = availableSkills();
  if (opts.command === "list") {
    console.log(`senior-skills ${version}: ${all.length} skills\n`);
    for (const skill of all) console.log(`  ${skill.padEnd(26)} ${describe(skill)}`);
    return;
  }

  let skills = all;
  if (opts.only) {
    const unknown = opts.only.filter((name) => !all.includes(name));
    if (unknown.length) throw new UsageError(`unknown skill(s): ${unknown.join(", ")}. Run "npx senior-skills list" to see them.`);
    skills = opts.only;
  }

  const targets = resolveTargets(opts, all);
  if (targets.length === 0) {
    console.log("No senior-skills installation found to update. Install with: npx senior-skills");
    return;
  }

  const stamp = timestamp();
  const verb = opts.command === "update" ? "updating" : "installing";
  console.log(`senior-skills ${version}: ${verb} ${skills.length} skill(s)\n`);
  const totals = { changed: 0, kept: false, backedUp: false };
  for (const target of targets) {
    const r = apply(skills, target, opts.command, opts.force, stamp);
    console.log(`  ✓ ${target.label.padEnd(15)} ${tildify(target.dir)}  (${summary(r)})`);
    if (r.foreign.length) {
      console.log(`    left alone (same name, not from senior-skills): ${r.foreign.join(", ")}. Use --force to replace them.`);
    }
    totals.changed += r.added.length + r.updated.length;
    totals.kept ||= r.kept.length > 0;
    totals.backedUp ||= r.backedUp.length > 0;
  }

  if (totals.backedUp) console.log(`\nCopies that differed were backed up to ${tildify(join(BACKUP_ROOT, stamp))}/ (safe to delete).`);
  if (totals.kept) console.log('\nSome installed skills differ from this version and were kept. To update them: npx senior-skills@latest update');
  console.log(
    totals.changed
      ? '\nRestart your agent session to load the changes. Then try: "Audit this repo\'s CI" or "Find the bugs that matter."'
      : "\nEverything is up to date.",
  );
}

try {
  main();
} catch (error) {
  if (error instanceof UsageError) {
    console.error(`senior-skills: ${error.message}\nRun "npx senior-skills --help" for usage.`);
    process.exit(2);
  }
  console.error(`senior-skills: ${error.message}`);
  process.exit(1);
}
