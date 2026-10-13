"""Exercise the preview CLI against real disposable repositories, without GitHub credentials."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "grafana_preview.py"


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "origin.git"
        self.repo = self.root / "repo"
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        self.git("init", "--bare", str(self.remote), cwd=self.root)
        self.git("init", "-b", "master", str(self.repo), cwd=self.root)
        self.git("remote", "add", "origin", str(self.remote))
        (self.repo / "grafana/dashboards").mkdir(parents=True)
        self.base = self.commit("grafana/dashboards/base.json", '{"title":"Base"}')
        self.git("push", "origin", "master")
        self.manifest = self.root / "pulls.json"
        self.state = self.root / "state.json"

    def git(self, *args, cwd=None):
        return subprocess.check_output(
            ["git", *args], cwd=cwd or self.repo, env=self.env, text=True, stderr=subprocess.PIPE
        ).strip()

    def commit(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git("add", "--", path)
        self.git("commit", "-m", "test change")
        return self.git("rev-parse", "HEAD")

    def pull(self, number, path, text):
        self.git("checkout", "-B", f"pr-{number}", self.base)
        sha = self.commit(path, text)
        self.git("push", "origin", f"HEAD:refs/pull/{number}/head")
        self.git("checkout", "master")
        return {
            "number": number,
            "state": "open",
            "base": {"ref": "master"},
            "head": {"sha": sha, "repo": {"full_name": "example/sentinel"}},
            "labels": [{"name": "grafana-preview"}],
        }

    def run_cli(self, command, pulls, success=True):
        self.manifest.write_text(json.dumps(pulls))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), command, str(self.manifest), str(self.state)],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0)
        return json.loads(self.state.read_text()) if self.state.exists() else {}

    def preview(self):
        return self.git("rev-parse", "refs/heads/staging-grafana", cwd=self.remote)

    def test_combines_prs_in_order_and_removes_unlabelled_changes(self):
        first = self.pull(1, "grafana/dashboards/one.json", '{"title":"One"}')
        second = self.pull(2, "grafana/dashboards/two.json", '{"title":"Two"}')
        self.run_cli("build", [second, first])
        state = self.run_cli("publish", [second, first])
        self.assertEqual([p["number"] for p in state["pulls"]], [1, 2])
        self.assertEqual(self.git("show", f"{self.preview()}:grafana/dashboards/one.json"), '{"title":"One"}')
        self.assertEqual(self.git("show", f"{self.preview()}:grafana/dashboards/two.json"), '{"title":"Two"}')
        first["labels"] = []
        self.run_cli("build", [first, second])
        self.run_cli("publish", [first, second])
        self.assertEqual(
            self.git("ls-tree", "-r", "--name-only", self.preview()),
            "grafana/dashboards/base.json\ngrafana/dashboards/two.json",
        )
        self.run_cli("build", [])
        self.run_cli("publish", [])
        self.assertEqual(self.preview(), self.base)

    def test_conflict_preserves_previous_preview_and_names_pr(self):
        first = self.pull(1, "grafana/dashboards/base.json", '{"title":"One"}')
        second = self.pull(2, "grafana/dashboards/base.json", '{"title":"Two"}')
        self.run_cli("build", [first])
        self.run_cli("publish", [first])
        previous = self.preview()
        state = self.run_cli("build", [first, second], success=False)
        self.assertIn("#2", state["error"])
        self.assertIn("conflict", state["error"].lower())
        self.assertEqual(self.preview(), previous)

    def test_closed_retargeted_and_unlabelled_prs_are_excluded(self):
        pulls = [self.pull(n, f"grafana/dashboards/{n}.json", "{}") for n in range(1, 4)]
        pulls[0]["state"] = "closed"
        pulls[1]["base"]["ref"] = "other"
        pulls[2]["labels"] = []
        self.run_cli("build", pulls)
        self.run_cli("publish", pulls)
        self.assertEqual(self.preview(), self.base)

    def test_moved_pr_head_is_rejected_before_build(self):
        pull = self.pull(1, "grafana/dashboards/one.json", "{}")
        pull["head"]["sha"] = self.base
        state = self.run_cli("build", [pull], success=False)
        self.assertIn("changed", state["error"])

    def test_label_change_during_build_prevents_publish(self):
        pull = self.pull(1, "grafana/dashboards/one.json", "{}")
        self.run_cli("build", [pull])
        state = self.run_cli("publish", [], success=False)
        self.assertIn("changed", state["error"])
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/staging-grafana"), "")

    def test_master_change_during_build_prevents_publish(self):
        self.run_cli("build", [])
        self.commit("grafana/dashboards/new.json", "{}")
        self.git("push", "origin", "master")
        state = self.run_cli("publish", [], success=False)
        self.assertIn("master changed", state["error"])

    def test_concurrent_branch_update_is_not_overwritten(self):
        self.run_cli("build", [])
        new = self.commit("grafana/dashboards/new.json", "{}")
        self.git("push", "origin", "HEAD:refs/heads/staging-grafana")
        self.run_cli("publish", [], success=False)
        self.assertEqual(self.preview(), new)

    def test_invalid_json_blocks_publish(self):
        pull = self.pull(1, "grafana/dashboards/broken.json", "{invalid")
        state = self.run_cli("build", [pull], success=False)
        self.assertIn("broken.json", state["error"])
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/staging-grafana"), "")

    def test_previous_participants_survive_coalesced_removals(self):
        first = self.pull(1, "grafana/dashboards/one.json", "{}")
        second = self.pull(2, "grafana/dashboards/two.json", "{}")
        self.run_cli("build", [first, second])
        self.run_cli("publish", [first, second])
        state = self.run_cli("build", [])
        self.assertEqual(state.get("previous_pulls"), [1, 2])
        self.run_cli("publish", [])
        self.assertEqual(self.preview(), self.base)

    def test_nonstandard_json_numbers_block_preview(self):
        pull = self.pull(1, "grafana/dashboards/nan.json", '{"value":NaN}')
        state = self.run_cli("build", [pull], success=False)
        self.assertIn("nan.json", state["error"])

    def test_same_snapshot_is_reproducible(self):
        pull = self.pull(1, "grafana/dashboards/one.json", "{}")
        first = self.run_cli("build", [pull])["candidate"]
        second = self.run_cli("build", [pull])["candidate"]
        self.assertEqual(first, second)

    def test_new_master_and_updated_pr_are_used_on_next_build(self):
        pull = self.pull(1, "grafana/dashboards/one.json", '{"title":"Old"}')
        self.run_cli("build", [pull])
        self.run_cli("publish", [pull])
        self.commit("grafana/dashboards/new-master.json", "{}")
        self.git("push", "origin", "master")
        self.git("checkout", "pr-1")
        pull["head"]["sha"] = self.commit("grafana/dashboards/one.json", '{"title":"New"}')
        self.git("push", "origin", "HEAD:refs/pull/1/head")
        self.git("checkout", "master")
        self.run_cli("build", [pull])
        self.run_cli("publish", [pull])
        self.assertEqual(self.git("show", f"{self.preview()}:grafana/dashboards/one.json"), '{"title":"New"}')
        self.assertEqual(self.git("show", f"{self.preview()}:grafana/dashboards/new-master.json"), "{}")

    def test_publish_without_build_is_rejected(self):
        state = self.run_cli("publish", [], success=False)
        self.assertIn("No successful preview build", state["error"])
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/staging-grafana"), "")

    def test_report_distinguishes_publication_from_import_and_failure(self):
        pull = self.pull(1, "grafana/dashboards/one.json", "{}")
        self.run_cli("build", [pull])
        self.run_cli("publish", [pull])
        self.env["GRAFANA_PREVIEW_URL"] = "https://grafana.example.invalid/"
        self.env["GITHUB_SERVER_URL"] = "https://github.com"
        self.env["GITHUB_REPOSITORY"] = "example/sentinel"
        self.env["GITHUB_RUN_ID"] = "123"
        output = subprocess.check_output(
            [sys.executable, str(SCRIPT), "report", str(self.manifest), str(self.state)],
            cwd=self.repo,
            env=self.env,
            text=True,
        )
        self.assertIn(self.preview(), output)
        self.assertIn(pull["head"]["sha"], output)
        self.assertIn("pending / not verified", output)
        self.assertIn("https://grafana.example.invalid/", output)
        self.assertIn("https://github.com/example/sentinel/actions/runs/123", output)
        self.state.write_text('{"error":"Conflict in #2"}')
        failed = subprocess.check_output(
            [sys.executable, str(SCRIPT), "report", str(self.manifest), str(self.state)],
            cwd=self.repo,
            env=self.env,
            text=True,
        )
        self.assertIn("may be stale", failed)
        self.assertIn("Conflict in #2", failed)
        self.assertNotIn("Published `", failed)

    def test_merge_never_changes_or_executes_checkout(self):
        pull = self.pull(1, "scripts/payload.py", 'raise SystemExit("do not execute")')
        self.run_cli("build", [pull])
        self.run_cli("publish", [pull])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertFalse((self.repo / "scripts/payload.py").exists())


if __name__ == "__main__":
    unittest.main()
