"""Run the real notification shell script against a disposable GitHub CLI boundary."""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CommentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state.json"
        self.state.write_text(
            json.dumps(
                {
                    "published": True,
                    "base": "a" * 40,
                    "candidate": "b" * 40,
                    "pulls": [{"number": 2, "sha": "c" * 40}],
                    "previous_pulls": [1],
                }
            )
        )
        self.calls = self.root / "calls.jsonl"
        shim = self.root / "gh"
        shim.write_text(
            textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            with open(os.environ["CALL_LOG"], "a") as log:
                log.write(json.dumps(sys.argv[1:]) + "\\n")
            if "--method" in sys.argv:
                if os.environ.get("FAIL_WRITE") == "1" and "PATCH" in sys.argv:
                    sys.exit(1)
                with open(os.environ["SUCCESS_LOG"], "a") as log:
                    log.write(json.dumps(sys.argv[1:]) + "\\n")
            elif any("/issues/1/comments?" in arg for arg in sys.argv):
                if os.environ.get("FAIL_LOOKUP") == "1":
                    sys.exit(1)
                # Mimic matching IDs arriving over many pages, exposing early pipe closure.
                if os.environ.get("MANY_IDS") == "1":
                    for _ in range(200):
                        os.write(1, b"901\\n" * 4096)
                else:
                    print("901")
        """)
        )
        shim.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "CALL_LOG": str(self.calls),
            "SUCCESS_LOG": str(self.root / "success.jsonl"),
            "GITHUB_REPOSITORY": "example/sentinel",
            "PREVIEW_STATE": str(self.state),
            "PREVIEW_PULLS": str(self.root / "pulls.json"),
            "PREVIEW_REPORT": str(self.root / "report.md"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"),
            "TRIGGER_PR": "3",
        }

    def run_comments(self, **overrides):
        return subprocess.run(
            ["bash", "scripts/grafana_preview_comments.sh"],
            cwd=ROOT,
            env={**self.env, **overrides},
            capture_output=True,
            text=True,
        )

    def successful_requests(self):
        path = self.root / "success.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_updates_previous_current_and_triggering_prs(self):
        result = self.run_comments()
        self.assertEqual(result.returncode, 0, result.stderr)
        requests = self.successful_requests()
        self.assertEqual(len(requests), 3)
        self.assertIn("repos/example/sentinel/issues/comments/901", requests[0])
        self.assertIn("PATCH", requests[0])
        self.assertIn("repos/example/sentinel/issues/2/comments", requests[1])
        self.assertIn("repos/example/sentinel/issues/3/comments", requests[2])
        self.assertIn("pending / not verified", (self.root / "summary.md").read_text())

    def test_one_failed_write_does_not_block_later_prs(self):
        result = self.run_comments(FAIL_WRITE="1")
        self.assertNotEqual(result.returncode, 0)
        requests = self.successful_requests()
        self.assertEqual(len(requests), 2, result.stderr)
        self.assertIn("repos/example/sentinel/issues/2/comments", requests[0])
        self.assertIn("repos/example/sentinel/issues/3/comments", requests[1])
        self.assertIn("#1", result.stderr)

    def test_failed_lookup_does_not_create_duplicate_or_block_later_prs(self):
        result = self.run_comments(FAIL_LOOKUP="1")
        self.assertNotEqual(result.returncode, 0)
        requests = self.successful_requests()
        self.assertEqual(len(requests), 2, result.stderr)
        self.assertIn("repos/example/sentinel/issues/2/comments", requests[0])
        self.assertIn("repos/example/sentinel/issues/3/comments", requests[1])
        self.assertIn("#1", result.stderr)

    def test_paginated_matching_comments_do_not_break_pipe(self):
        result = self.run_comments(MANY_IDS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.successful_requests()), 3)


if __name__ == "__main__":
    unittest.main()
