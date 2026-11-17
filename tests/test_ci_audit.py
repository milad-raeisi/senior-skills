"""Unit tests for skills/ci-auditor/scripts/ci_audit.py (standard library only).

Run: python3 -m unittest discover -s tests -v
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the skill folder that installers copy

SCRIPT =Path(__file__).resolve().parent.parent / "skills" / "ci-auditor" / "scripts" / "ci_audit.py"
spec = importlib.util.spec_from_file_location("ci_audit", SCRIPT)
ci_audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ci_audit  # dataclasses look the module up here on Python < 3.14
spec.loader.exec_module(ci_audit)


def step(name, start, end):
    return {"name": name, "started_at": f"2026-11-01T10:{start}Z", "completed_at": f"2026-11-01T10:{end}Z"}


def make_job(name="test", workflow="CI", run_id=1, conclusion="success", created="00:00",
             started="00:30", completed="05:00", steps=None):
    return {
        "name": name,
        "workflow_name": workflow,
        "run_id": run_id,
        "conclusion": conclusion,
        "labels": ["ubuntu-latest"],
        "created_at": f"2026-11-01T10:{created}Z",
        "started_at": f"2026-11-01T10:{started}Z",
        "completed_at": f"2026-11-01T10:{completed}Z",
        "steps": steps if steps is not None else [
            step("Set up job", "00:30", "00:32"),
            step("Run actions/checkout@v4", "00:32", "00:35"),
            step("Run npm ci", "00:35", "01:35"),
            step("Run npm test", "01:35", "04:58"),
            step("Post Run actions/checkout@v4", "04:58", "04:59"),
            step("Complete job", "04:59", "05:00"),
        ],
    }


class ClassifierTest(unittest.TestCase):
    def setUp(self):
        self.c = ci_audit.Classifier.build()

    def test_setup_steps(self):
        for name in [
            "Set up job", "Complete job", "Run actions/checkout@v4", "Check out repository",
            "Run actions/setup-node@v4", "Set up Python 3.12", "Use Node.js 20.x",
            "Run actions/cache@v4", "Run Swatinem/rust-cache@v2", "Install dependencies",
            "Run npm ci", "Run pnpm install", "Run uv sync --locked", "Run go mod download",
            "Post Run actions/cache@v4", "Initialize containers", "Log in to GHCR",
            "Set up Docker Buildx", "Run actions/download-artifact@v4", "Run dtolnay/rust-toolchain@stable",
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.c.bucket(name), "setup")

    def test_run_steps(self):
        for name in ["Run npm test", "Build", "Run cargo test --all", "Lint", "Deploy to production", "Run pytest -x"]:
            with self.subTest(name=name):
                self.assertEqual(self.c.bucket(name), "run")

    def test_overrides(self):
        c = ci_audit.Classifier.build(extra_setup=[r"^prepare db$"], force_run=[r"install script smoke"])
        self.assertEqual(c.bucket("Prepare DB"), "setup")
        self.assertEqual(c.bucket("Install script smoke test"), "run")


class TimeJobTest(unittest.TestCase):
    def test_three_way_split(self):
        t = ci_audit.time_job(make_job(), ci_audit.Classifier.build())
        self.assertEqual(t.queue, 30)
        # set up 2 + checkout 3 + npm ci 60 + post 1 + complete 1
        self.assertEqual(t.setup, 67)
        self.assertEqual(t.run, 270 - 67)
        self.assertEqual(t.total, 300)
        self.assertEqual(t.key, "CI › test")

    def test_excluded_jobs(self):
        c = ci_audit.Classifier.build()
        self.assertIsNone(ci_audit.time_job(make_job(conclusion="skipped"), c))
        self.assertIsNone(ci_audit.time_job(make_job(conclusion="cancelled"), c))
        job = make_job()
        job["started_at"] = None
        self.assertIsNone(ci_audit.time_job(job, c))

    def test_failed_jobs_are_included(self):
        self.assertIsNotNone(ci_audit.time_job(make_job(conclusion="failure"), ci_audit.Classifier.build()))

    def test_setup_never_exceeds_execution(self):
        steps = [step("Run npm ci", "00:30", "09:00")]  # step timestamps past job completion
        t = ci_audit.time_job(make_job(steps=steps), ci_audit.Classifier.build())
        self.assertEqual(t.setup, 270)
        self.assertEqual(t.run, 0)

    def test_negative_queue_is_clamped(self):
        t = ci_audit.time_job(make_job(created="01:00", started="00:30"), ci_audit.Classifier.build())
        self.assertEqual(t.queue, 0)

    def test_group_matrix(self):
        job = make_job(name="test (ubuntu-latest, 20)")
        self.assertEqual(ci_audit.job_key(job, group_matrix=False), "CI › test (ubuntu-latest, 20)")
        self.assertEqual(ci_audit.job_key(job, group_matrix=True), "CI › test")


class AnalyzeTest(unittest.TestCase):
    def jobs(self):
        fast = [make_job(name="lint", run_id=i, completed="01:00") for i in range(3)]
        slow = [make_job(name="test", run_id=i) for i in range(3)]
        once = [make_job(name="release", run_id=9, completed="20:00")]
        return fast + slow + once

    def test_ranking_and_min_runs(self):
        c = ci_audit.Classifier.build()
        result = ci_audit.analyze(self.jobs(), c, top=5, rank_by="median", group_matrix=False)
        self.assertEqual([s.key for s in result["slowest"]], ["CI › release", "CI › test", "CI › lint"])
        result = ci_audit.analyze(self.jobs(), c, top=5, rank_by="median", group_matrix=False, min_runs=2)
        self.assertEqual([s.key for s in result["slowest"]], ["CI › test", "CI › lint"])

    def test_totals_add_up(self):
        result = ci_audit.analyze(self.jobs(), ci_audit.Classifier.build(), 5, "sum", False)
        totals = result["totals"]
        self.assertEqual(result["jobs_analyzed"], 7)
        self.assertAlmostEqual(sum(totals.values()), sum(s.sum_total for s in result["slowest"]))


class ParsingAndOutputTest(unittest.TestCase):
    def test_parse_json_stream(self):
        self.assertEqual(ci_audit.parse_json_stream('{"jobs": [1]}\n{"jobs": [2]}'), [{"jobs": [1]}, {"jobs": [2]}])
        self.assertEqual(ci_audit.parse_json_stream('{"a":1}{"b":2}'), [{"a": 1}, {"b": 2}])
        self.assertEqual(ci_audit.parse_json_stream(""), [])

    def test_markdown_escapes_pipes(self):
        result = ci_audit.analyze([make_job(name="check | publish")], ci_audit.Classifier.build(), 5, "median", False)
        result["failed_runs"] = []
        report = ci_audit.render_markdown("o/r", [{"createdAt": "2026-11-01T10:00:00Z"}], result)
        self.assertIn("CI › check \\| publish", report)

    def test_end_to_end_from_raw(self):
        raw = {"repo": "octo/demo", "runs": [{"databaseId": 1, "createdAt": "2026-11-01T10:00:00Z"}],
               "jobs": [make_job()], "failed_runs": [42]}
        with tempfile.TemporaryDirectory() as tmp:
            raw_path, out_path = Path(tmp, "raw.json"), Path(tmp, "report.md")
            raw_path.write_text(json.dumps(raw))
            with contextlib.redirect_stderr(io.StringIO()):
                code = ci_audit.main(["--from-raw", str(raw_path), "--out", str(out_path)])
            self.assertEqual(code, 0)
            report = out_path.read_text()
        self.assertIn("# CI audit: octo/demo", report)
        self.assertIn("| 1 | CI › test | 1 | 30 | 67 | 203 | 300 | 300 |", report)
        self.assertIn("could not be fetched", report)

    def test_json_output(self):
        raw = {"repo": "octo/demo", "runs": [{"databaseId": 1, "createdAt": "2026-11-01T10:00:00Z"}], "jobs": [make_job()]}
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp, "raw.json")
            raw_path.write_text(json.dumps(raw))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                ci_audit.main(["--from-raw", str(raw_path), "--format", "json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["slowest"][0]["median_seconds"], {"queue": 30, "setup": 67, "run": 203, "total": 300})


if __name__ == "__main__":
    unittest.main()
