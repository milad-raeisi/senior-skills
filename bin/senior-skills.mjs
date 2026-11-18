#!/usr/bin/env node
// senior-skills installer: copies the skills shipped in this package into your coding agents'
// skills folders. No dependencies. Existing skills are never overwritten silently.
//
//   npx senior-skills                         install for every agent found on this machine
//   npx senior-skills --agent claude          one agent (repeatable, or comma-separated, or "all")
//   npx senior-skills --dir ./.agents/skills  any folder, e.g. project-level skills
//   npx senior-skills --only bug-triage,ci-auditor
//   npx senior-skills --force                 replace existing copies (old ones are moved to *.bak-<time>)
//   npx senior-skills --list                  show the skills in this package

import { cpSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, renameSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PKG_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SKILLS_DIR = join(PKG_ROOT, "skills");
const { version } = JSON.parse(readFileSync(join(PKG_ROOT, "package.json"), "utf8"));

const HOME = homedir();
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

const HELP = `senior-skills ${version}: staff-engineer judgment for coding agents

Usage: npx senior-skills [options]

With no options, installs every skill for each agent found on this machine
(falls back to Claude Code if none is found).

Options:
  --agent <name>   ${Object.keys(AGENTS).join(", ")}, or all (repeatable or comma-separated)
  --dir <path>     install into any folder, e.g. ./.agents/skills (repeatable)
  --only <a,b>     install only these skills
  --force          replace existing copies; old ones are moved to <name>.bak-<time>
  --list           list the skills in this package and exit
  -v, --version    print the version
  -h, --help       show this help

Docs: https://github.com/milad-raeisi/senior-skills`;

class UsageError extends Error {}

function parseArgs(argv) {
  const opts = { agents: [], dirs: [], only: null, force: false, list: false };
  const value = (flag, i) => {
    if (i >= argv.length || argv[i].startsWith("-")) throw new UsageError(`${flag} needs a value`);
    return argv[i];
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") opts.help = true;
    else if (arg === "-v" || arg === "--version") opts.version = true;
    else if (arg === "--list") opts.list = true;
    else if (arg === "--force") opts.force = true;
    else if (arg === "--agent") opts.agents.push(...value(arg, ++i).split(",").filter(Boolean));
    else if (arg === "--dir") opts.dirs.push(value(arg, ++i));
    else if (arg === "--only") opts.only = value(arg, ++i).split(",").filter(Boolean);
    else throw new UsageError(`unknown option: ${arg}`);
  }
  return opts;
}

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

function resolveTargets(opts) {
  const targets = [];
  let names = opts.agents.flatMap((name) => (name === "all" ? Object.keys(AGENTS) : [name]));
  for (const name of names) {
    if (!AGENTS[name]) throw new UsageError(`unknown agent: ${name} (choose from ${Object.keys(AGENTS).join(", ")}, all)`);
  }
  if (names.length === 0 && opts.dirs.length === 0) {
    names = Object.keys(AGENTS).filter((name) => existsSync(AGENTS[name].marker));
    if (names.length === 0) names = ["claude"];
  }
  for (const name of [...new Set(names)]) targets.push({ label: AGENTS[name].label, dir: AGENTS[name].dir });
  for (const dir of opts.dirs) targets.push({ label: dir, dir: resolve(dir) });
  return targets;
}

function exists(path) {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
}

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function install(skills, target, force, stamp) {
  mkdirSync(target.dir, { recursive: true });
  const result = { installed: 0, skipped: [], backedUp: [] };
  for (const skill of skills) {
    const dest = join(target.dir, skill);
    if (exists(dest)) {
      if (!force) {
        result.skipped.push(skill);
        continue;
      }
      renameSync(dest, `${dest}.bak-${stamp}`);
      result.backedUp.push(skill);
    }
    cpSync(join(SKILLS_DIR, skill), dest, {
      recursive: true,
      filter: (src) => basename(src) !== "__pycache__" && !src.endsWith(".pyc"),
    });
    result.installed++;
  }
  return result;
}

function tildify(path) {
  return path.startsWith(HOME) ? `~${path.slice(HOME.length)}` : path;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) return console.log(HELP);
  if (opts.version) return console.log(version);

  const all = availableSkills();
  if (opts.list) {
    console.log(`senior-skills ${version}: ${all.length} skills\n`);
    for (const skill of all) console.log(`  ${skill.padEnd(26)} ${describe(skill)}`);
    return;
  }

  let skills = all;
  if (opts.only) {
    const unknown = opts.only.filter((name) => !all.includes(name));
    if (unknown.length) throw new UsageError(`unknown skill(s): ${unknown.join(", ")}. Run --list to see them.`);
    skills = opts.only;
  }

  const targets = resolveTargets(opts);
  const stamp = timestamp();
  console.log(`senior-skills ${version}: installing ${skills.length} skill(s)\n`);
  let skippedAny = false;
  for (const target of targets) {
    const r = install(skills, target, opts.force, stamp);
    console.log(`  ✓ ${target.label.padEnd(15)} ${tildify(target.dir)}  (${r.installed} installed${r.skipped.length ? `, ${r.skipped.length} already there` : ""})`);
    if (r.backedUp.length) console.log(`    previous copies moved to *.bak-${stamp}: ${r.backedUp.join(", ")}`);
    if (r.skipped.length) skippedAny = true;
  }
  if (skippedAny) console.log("\nSome skills were already installed and left untouched. Re-run with --force to update them.");
  console.log('\nRestart your agent session to load the skills. Then try: "Audit this repo\'s CI" or "Find the bugs that matter."');
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
