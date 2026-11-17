#!/usr/bin/env python3
"""Where does GitHub Actions time go?

Splits every job of the last N completed workflow runs into three parts:

  queue  waiting for a runner           job.started_at - job.created_at
  setup  getting ready to work          steps whose names match setup patterns: "Set up job",
                                        checkout, toolchain setup, dependency install, cache
                                        restore/save, service containers, post-job cleanup
  run    doing the actual task          the rest of the job's execution time

and reports the slowest jobs with median seconds per part.

Read-only: it only sends GET requests through the GitHub CLI (gh).

Usage:
  ci_audit.py                                   current repo, last 150 runs, top 5
  ci_audit.py --repo OWNER/REPO --runs 150 --top 5 --out ci-audit.md
  ci_audit.py --workflow ci.yml --branch main   limit to one workflow / branch
  ci_audit.py --save-raw raw.json               keep fetched data for re-analysis
  ci_audit.py --from-raw raw.json               analyze saved data without the network
  ci_audit.py --format json                     machine-readable output
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Step names are matched case-insensitively with re.search.
# Unnamed steps appear as "Run <action or command>", e.g. "Run actions/checkout@v4", "Run npm ci".
DEFAULT_SETUP_PATTERNS = [
    r"^set up job$",
    r"^complete job$",
    r"^post ",  # GitHub-generated cleanup steps: "Post Run actions/cache@v4"
    r"^(initialize|stop) containers$",
    r"check ?out",  # actions/checkout, "Checkout", "Check out repository"
    r"setup-[a-z]",  # actions/setup-node, astral-sh/setup-uv, ruby/setup-ruby ...
    r"action-setup",  # pnpm/action-setup
    r"\bset ?up\b",  # "Set up Python 3.12", "Setup Node"
    r"^use (node|python|go|java|ruby|bun|deno|jdk)",
    r"toolchain",
    r"\bcache\b",  # actions/cache, Swatinem/rust-cache, "Restore cache"
    r"\binstall\b",  # "Install dependencies", "Run pip install ..."
    r"\b(npm|pnpm|yarn|bun)\s+(ci|i)\b",
    r"^run (yarn|pnpm|bun)$",
    r"\b(uv sync|poetry install|pipenv install|bundle install|go mod download|cargo fetch"
    r"|composer install|dotnet restore|mix deps\.get|flutter pub get|dart pub get)\b",
    r"\blog ?in to\b|docker/login-action",
    r"buildx|qemu",
    r"download[- ]artifact",
]

EXCLUDED_CONCLUSIONS = {"skipped", "cancelled"}


class GhError(RuntimeError):
    pass


# --------------------------------------------------------------------------- fetching


def gh(args: list[str]) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        sys.exit("error: the GitHub CLI (gh) is not installed. Install it from https://cli.github.com")
    if proc.returncode != 0:
        raise GhError(proc.stderr.strip() or f"gh {' '.join(args)} failed with exit code {proc.returncode}")
    return proc.stdout


def parse_json_stream(text: str) -> list:
    """Parse one or more concatenated JSON documents (what `gh api --paginate` prints)."""
    decoder = json.JSONDecoder()
    values, idx, text = [], 0, text.strip()
    while idx < len(text):
        value, idx = decoder.raw_decode(text, idx)
        values.append(value)
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return values


def current_repo() -> str:
    return gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()


def fetch_runs(repo: str, limit: int, workflow: str | None, branch: str | None) -> list[dict]:
    args = [
        "run", "list", "--repo", repo, "--limit", str(limit), "--status", "completed",
        "--json", "databaseId,workflowName,createdAt,conclusion,event,headBranch,attempt",
    ]
    if workflow:
        args += ["--workflow", workflow]
    if branch:
        args += ["--branch", branch]
    return json.loads(gh(args) or "[]")


# Large runs (100+ jobs with their steps) intermittently return HTTP 502 at per_page=100,
# so each retry asks for smaller pages after a short backoff.
PAGE_SIZES = (100, 30, 30, 15)


def fetch_jobs(repo: str, run: dict) -> list[dict]:
    for attempt, page_size in enumerate(PAGE_SIZES, start=1):
        endpoint = f"repos/{repo}/actions/runs/{run['databaseId']}/jobs?per_page={page_size}"
        try:
            pages = parse_json_stream(gh(["api", "--paginate", endpoint]))
            break
        except GhError:
            if attempt == len(PAGE_SIZES):
                raise
            time.sleep(2 ** attempt)
    jobs = [job for page in pages for job in page.get("jobs", [])]
    for job in jobs:
        job.setdefault("workflow_name", run.get("workflowName"))
    return jobs


def fetch_all(repo: str, runs: list[dict], concurrency: int) -> tuple[list[dict], list[int]]:
    """Return all jobs plus the IDs of runs whose jobs could not be fetched."""
    jobs: list[dict] = []
    failed: list[int] = []

    def one(run: dict) -> list[dict] | None:
        try:
            return fetch_jobs(repo, run)
        except GhError as exc:
            print(f"warning: run {run['databaseId']}: {exc}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for i, (run, run_jobs) in enumerate(zip(runs, pool.map(one, runs)), start=1):
            if run_jobs is None:
                failed.append(run["databaseId"])
            else:
                jobs.extend(run_jobs)
            if i % 25 == 0 or i == len(runs):
                print(f"  fetched jobs for {i}/{len(runs)} runs", file=sys.stderr)
    if failed:
        print(f"warning: could not fetch jobs for {len(failed)} run(s); they are excluded", file=sys.stderr)
    return jobs, failed


# --------------------------------------------------------------------------- analysis


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def seconds(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    return max(0.0, (ts(end) - ts(start)).total_seconds())


@dataclass
class Classifier:
    setup: list[re.Pattern]
    run: list[re.Pattern]

    @classmethod
    def build(cls, extra_setup: list[str] | None = None, force_run: list[str] | None = None) -> "Classifier":
        compile_all = lambda patterns: [re.compile(p, re.IGNORECASE) for p in patterns]
        return cls(compile_all(DEFAULT_SETUP_PATTERNS + (extra_setup or [])), compile_all(force_run or []))

    def bucket(self, step_name: str) -> str:
        if any(p.search(step_name) for p in self.run):
            return "run"
        if any(p.search(step_name) for p in self.setup):
            return "setup"
        return "run"


@dataclass
class JobTiming:
    key: str
    run_id: int
    conclusion: str
    labels: list[str]
    queue: float
    setup: float
    run: float
    steps: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.queue + self.setup + self.run


MATRIX_SUFFIX = re.compile(r"\s*\(.*\)\s*$")


def job_key(job: dict, group_matrix: bool) -> str:
    name = job.get("name") or "?"
    if group_matrix:
        name = MATRIX_SUFFIX.sub("", name) or name
    return f"{job.get('workflow_name') or '?'} › {name}"


def time_job(job: dict, classifier: Classifier, group_matrix: bool = False) -> JobTiming | None:
    if job.get("conclusion") in EXCLUDED_CONCLUSIONS:
        return None
    if not job.get("started_at") or not job.get("completed_at"):
        return None
    queue = seconds(job.get("created_at"), job["started_at"])
    execution = seconds(job["started_at"], job["completed_at"])
    setup, steps = 0.0, []
    for step in job.get("steps") or []:
        duration = seconds(step.get("started_at"), step.get("completed_at"))
        bucket = classifier.bucket(step.get("name") or "")
        steps.append((step.get("name") or "?", bucket, duration))
        if bucket == "setup":
            setup += duration
    setup = min(setup, execution)  # 1-second timestamp resolution can make steps sum past the job
    return JobTiming(
        key=job_key(job, group_matrix),
        run_id=job.get("run_id", 0),
        conclusion=job.get("conclusion") or "?",
        labels=list(job.get("labels") or []),
        queue=queue,
        setup=setup,
        run=execution - setup,
        steps=steps,
    )


def p90(values: list[float]) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=10, method="inclusive")[-1]


@dataclass
class JobStats:
    key: str
    n: int
    queue: float
    setup: float
    run: float
    total: float
    p90_total: float
    sum_total: float
    labels: list[str]
    top_steps: list[tuple[str, str, float]]


def aggregate(timings: list[JobTiming]) -> list[JobStats]:
    groups: dict[str, list[JobTiming]] = {}
    for t in timings:
        groups.setdefault(t.key, []).append(t)
    stats = []
    for key, items in groups.items():
        step_durations: dict[tuple[str, str], list[float]] = {}
        for t in items:
            for name, bucket, duration in t.steps:
                step_durations.setdefault((name, bucket), []).append(duration)
        top_steps = sorted(
            ((name, bucket, statistics.median(d)) for (name, bucket), d in step_durations.items()),
            key=lambda s: s[2],
            reverse=True,
        )[:4]
        labels = sorted({label for t in items for label in t.labels})
        totals = [t.total for t in items]
        stats.append(
            JobStats(
                key=key,
                n=len(items),
                queue=statistics.median(t.queue for t in items),
                setup=statistics.median(t.setup for t in items),
                run=statistics.median(t.run for t in items),
                total=statistics.median(totals),
                p90_total=p90(totals),
                sum_total=sum(totals),
                labels=labels,
                top_steps=top_steps,
            )
        )
    return stats


RANKINGS = {
    "median": lambda s: s.total,
    "p90": lambda s: s.p90_total,
    "sum": lambda s: s.sum_total,
}


def analyze(jobs: list[dict], classifier: Classifier, top: int, rank_by: str, group_matrix: bool,
            min_runs: int = 1) -> dict:
    timings = [t for t in (time_job(j, classifier, group_matrix) for j in jobs) if t]
    eligible = [s for s in aggregate(timings) if s.n >= min_runs]
    stats = sorted(eligible, key=RANKINGS[rank_by], reverse=True)
    totals = {part: sum(getattr(t, part) for t in timings) for part in ("queue", "setup", "run")}
    return {
        "jobs_total": len(jobs),
        "jobs_analyzed": len(timings),
        "jobs_excluded": len(jobs) - len(timings),
        "runs_with_jobs": len({t.run_id for t in timings}),
        "totals": totals,
        "rank_by": rank_by,
        "min_runs": min_runs,
        "slowest": stats[:top],
        "job_names": len(stats),
    }


# --------------------------------------------------------------------------- output


def human(secs: float) -> str:
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def cell(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return text.replace("|", "\\|")


def window(runs: list[dict]) -> str:
    dates = sorted(r["createdAt"][:10] for r in runs if r.get("createdAt"))
    return f"{dates[0]} to {dates[-1]}" if dates else "unknown dates"


def render_markdown(repo: str, runs: list[dict], result: dict) -> str:
    totals = result["totals"]
    grand = sum(totals.values()) or 1.0
    rank_label = {"median": "median total", "p90": "p90 total", "sum": "total job-time"}[result["rank_by"]]
    if result.get("min_runs", 1) > 1:
        rank_label += f", jobs with at least {result['min_runs']} executions"
    out = [
        f"# CI audit: {repo}",
        "",
        f"**Window:** {len(runs)} completed runs, {window(runs)}. "
        f"**Jobs analyzed:** {result['jobs_analyzed']} "
        f"({result['jobs_excluded']} skipped, cancelled, or incomplete jobs excluded).",
        "",
        *(
            [f"**Warning:** job data for {len(result['failed_runs'])} run(s) could not be fetched after retries "
             f"and is missing from these numbers: {', '.join(map(str, result['failed_runs']))}.", ""]
            if result.get("failed_runs") else []
        ),
        "**Method:** queue = job start minus job creation; setup = steps classified as setup "
        "(set up job, checkout, toolchains, dependency install, cache restore/save, cleanup); "
        "run = the rest of the job's execution time.",
        "",
        "## Where the time goes",
        "",
        "| Part | Job-time (sum) | Share |",
        "|---|---:|---:|",
        f"| Queue: waiting for a runner | {human(totals['queue'])} | {totals['queue'] / grand:.0%} |",
        f"| Setup: checkout, toolchains, dependencies, cache | {human(totals['setup'])} | {totals['setup'] / grand:.0%} |",
        f"| Run: the actual task | {human(totals['run'])} | {totals['run'] / grand:.0%} |",
        "",
        f"## {len(result['slowest'])} slowest jobs (ranked by {rank_label}; seconds are medians per execution)",
        "",
        "| # | Workflow › Job | Runs | Queue s | Setup s | Run s | Total s | p90 total s |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for i, s in enumerate(result["slowest"], start=1):
        out.append(
            f"| {i} | {cell(s.key)} | {s.n} | {s.queue:.0f} | {s.setup:.0f} | {s.run:.0f} | {s.total:.0f} | {s.p90_total:.0f} |"
        )
    out += ["", "_Medians are computed per column, so the parts may not add up exactly to the median total._", ""]
    out += ["## Details", ""]
    for i, s in enumerate(result["slowest"], start=1):
        share = s.setup / s.total if s.total else 0.0
        steps = " · ".join(f"`{name}` {secs:.0f}s ({bucket})" for name, bucket, secs in s.top_steps) or "no step data"
        out += [
            f"### {i}. {s.key}",
            "",
            f"- Runner labels: {', '.join(f'`{label}`' for label in s.labels) or 'unknown'}",
            f"- Median split: queue {s.queue:.0f}s · setup {s.setup:.0f}s · run {s.run:.0f}s "
            f"({share:.0%} of the median total is setup)",
            f"- Total job-time in window: {human(s.sum_total)} across {s.n} executions",
            f"- Biggest steps (median): {steps}",
            "",
        ]
    out.append(
        "_Steps are classified by name. Check the biggest-steps lines; if a step is in the wrong bucket, "
        "re-run with `--setup-pattern REGEX` or `--run-pattern REGEX`._"
    )
    return "\n".join(out) + "\n"


def render_json(repo: str, runs: list[dict], result: dict) -> str:
    payload = {
        "repo": repo,
        "runs": len(runs),
        "window": window(runs),
        **{k: v for k, v in result.items() if k != "slowest"},
        "slowest": [
            {
                "job": s.key,
                "executions": s.n,
                "median_seconds": {"queue": s.queue, "setup": s.setup, "run": s.run, "total": s.total},
                "p90_total_seconds": s.p90_total,
                "sum_total_seconds": s.sum_total,
                "runner_labels": s.labels,
                "top_steps": [{"name": n, "bucket": b, "median_seconds": d} for n, b, d in s.top_steps],
            }
            for s in result["slowest"]
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split GitHub Actions job time into queue, setup, and run.")
    parser.add_argument("--repo", help="OWNER/REPO (default: the repository in the current directory)")
    parser.add_argument("--runs", type=int, default=150, help="number of recent completed runs (default 150)")
    parser.add_argument("--top", type=int, default=5, help="number of slowest jobs to report (default 5)")
    parser.add_argument("--workflow", help="limit to one workflow (file name, ID, or name)")
    parser.add_argument("--branch", help="limit to one branch")
    parser.add_argument("--rank-by", choices=sorted(RANKINGS), default="median",
                        help="median total per execution (default), p90 total, or sum of job-time")
    parser.add_argument("--min-runs", type=int, default=1, metavar="N",
                        help="only rank jobs with at least N executions in the window (default 1)")
    parser.add_argument("--group-matrix", action="store_true",
                        help="merge matrix variants: 'test (ubuntu, 18)' and 'test (macos, 20)' become 'test'")
    parser.add_argument("--setup-pattern", action="append", default=[], metavar="REGEX",
                        help="extra regex for steps that count as setup (repeatable)")
    parser.add_argument("--run-pattern", action="append", default=[], metavar="REGEX",
                        help="regex for steps that always count as run, overriding setup patterns (repeatable)")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    parser.add_argument("--out", help="write the report to this file instead of stdout")
    parser.add_argument("--save-raw", metavar="FILE", help="save fetched runs and jobs as JSON")
    parser.add_argument("--from-raw", metavar="FILE", help="analyze a file written by --save-raw (no network)")
    parser.add_argument("--concurrency", type=int, default=8, help="parallel API requests (default 8)")
    args = parser.parse_args(argv)

    try:
        if args.from_raw:
            with open(args.from_raw, encoding="utf-8") as fh:
                raw = json.load(fh)
            repo, runs, jobs = raw["repo"], raw["runs"], raw["jobs"]
            failed = raw.get("failed_runs", [])
        else:
            repo = args.repo or current_repo()
            print(f"Fetching the last {args.runs} completed runs of {repo} ...", file=sys.stderr)
            runs = fetch_runs(repo, args.runs, args.workflow, args.branch)
            if not runs:
                print(f"No completed workflow runs found for {repo}.", file=sys.stderr)
                return 1
            jobs, failed = fetch_all(repo, runs, args.concurrency)
            if args.save_raw:
                with open(args.save_raw, "w", encoding="utf-8") as fh:
                    json.dump({"repo": repo, "fetched_at": datetime.now(timezone.utc).isoformat(),
                               "runs": runs, "jobs": jobs, "failed_runs": failed}, fh)
    except GhError as exc:
        print(f"error: {exc}\nCheck `gh auth status` and that the repository has GitHub Actions runs.", file=sys.stderr)
        return 2

    classifier = Classifier.build(args.setup_pattern, args.run_pattern)
    result = analyze(jobs, classifier, args.top, args.rank_by, args.group_matrix, args.min_runs)
    result["failed_runs"] = failed
    if not result["jobs_analyzed"]:
        print("No completed, non-skipped jobs to analyze.", file=sys.stderr)
        return 1
    report = (render_json if args.format == "json" else render_markdown)(repo, runs, result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"Report written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
