"""Build a Grafana preview from GitHub PR snapshots without checking out PR code.

GitHub transport belongs to the workflow (gh api). This CLI only consumes JSON
snapshots and operates on Git objects; it needs Python 3.11+ and Git 2.38+.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PREVIEW_REF = "refs/heads/staging-grafana"


def git(*args, input=None, env=None):
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        input=input,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
    return result.stdout.strip()


def selected_pulls(path):
    selected = []
    for pull in json.loads(path.read_text()):
        if (
            pull["state"] == "open"
            and pull["base"]["ref"] == "master"
            and any(label["name"] == "grafana-preview" for label in pull["labels"])
        ):
            number, sha = pull["number"], pull["head"]["sha"]
            if type(number) is not int or number <= 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("Invalid PR number or commit SHA")
            selected.append({"number": number, "sha": sha})
    return sorted(selected, key=lambda pull: pull["number"])


def remote_head(ref):
    result = git("ls-remote", "--refs", "origin", ref)
    return result.split()[0] if result else ""


def reject_json_constant(value):
    raise ValueError(f"nonstandard JSON constant: {value}")


def build(pulls, state):
    state["pulls"] = pulls
    state["previous"] = remote_head(PREVIEW_REF)
    state["previous_pulls"] = []
    if state["previous"]:
        git("fetch", "--no-tags", "origin", PREVIEW_REF)
        state["previous"] = git("rev-parse", "FETCH_HEAD")
        # Only our generated top-of-first-parent chain describes the old preview.
        for subject in git("log", "--first-parent", "--format=%s", state["previous"]).splitlines():
            match = re.fullmatch(r"Grafana preview: merge PR #([1-9][0-9]*)", subject)
            if not match:
                break
            state["previous_pulls"].append(int(match[1]))
        state["previous_pulls"].sort()
    git("fetch", "--no-tags", "origin", "+refs/heads/master:refs/remotes/origin/master")
    state["base"] = git("rev-parse", "refs/remotes/origin/master")
    candidate = state["base"]
    for pull in pulls:
        number, sha = pull["number"], pull["sha"]
        git("fetch", "--no-tags", "origin", f"refs/pull/{number}/head")
        if git("rev-parse", "FETCH_HEAD") != sha:
            raise RuntimeError(f"PR #{number} changed during the build; rerun the workflow.")
        try:
            tree = git("merge-tree", "--write-tree", candidate, sha).splitlines()[0]
        except RuntimeError as exc:
            raise RuntimeError(f"Merge conflict or merge failure in PR #{number}.\n{exc}") from exc
        # Stable timestamps make identical input snapshots produce identical commits.
        timestamp = max(int(git("show", "-s", "--format=%ct", parent)) for parent in (candidate, sha))
        commit_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_AUTHOR_DATE": f"{timestamp} +0000",
            "GIT_COMMITTER_DATE": f"{timestamp} +0000",
        }
        candidate = git(
            "commit-tree",
            tree,
            "-p",
            candidate,
            "-p",
            sha,
            input=f"Grafana preview: merge PR #{number}\n",
            env=commit_env,
        )
    # Inspect blobs directly. PR scripts, workflows, and Git hooks never run.
    entries = git("ls-tree", "-r", "-z", candidate, "--", "grafana/dashboards")
    for entry in entries.split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        if not name.endswith(".json"):
            continue
        mode, kind, oid = metadata.split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise RuntimeError(f"Dashboard must be a regular JSON file: {name}")
        try:
            dashboard = json.loads(git("cat-file", "blob", oid), parse_constant=reject_json_constant)
            if not isinstance(dashboard, dict):
                raise ValueError("expected a JSON object")
        except ValueError as exc:
            raise RuntimeError(f"Invalid dashboard JSON in {name}: {exc}") from exc
    state["candidate"] = candidate


def publish(pulls, state):
    if state.get("error") or "candidate" not in state:
        raise RuntimeError("No successful preview build to publish.")
    if pulls != state["pulls"]:
        raise RuntimeError("Preview PRs changed during the build; rerun the workflow.")
    if remote_head("refs/heads/master") != state["base"]:
        raise RuntimeError("master changed during the build; rerun the workflow.")
    git(
        "push",
        f"--force-with-lease={PREVIEW_REF}:{state['previous']}",
        "origin",
        f"{state['candidate']}:{PREVIEW_REF}",
    )
    state["published"] = True


def report(state):
    lines = ["<!-- grafana-preview -->", "### Shared Grafana preview", ""]
    if state.get("published"):
        lines += [
            f"Published `{state['candidate']}` to `staging-grafana`.",
            "Grafana import is **pending / not verified by this workflow**. Wait for Git Sync before reviewing.",
        ]
    else:
        lines += [
            "**Preview update failed. The previous preview may be stale.**",
            "The workflow did not confirm a new branch publication. See the run for details.",
        ]
        if state.get("error"):
            lines += ["", "```text", state["error"].replace("```", "~~~")[:4000], "```"]
    if state.get("base"):
        lines += ["", f"Base: `master` at `{state['base']}`."]
    lines += ["", "PR revisions in this build attempt:"]
    lines += [f"- #{pull['number']} at `{pull['sha']}`" for pull in state.get("pulls", [])] or [
        "- None; a successful publication resets the preview to master."
    ]
    lines += ["", "Only the PRs listed above are included after a successful publication."]
    url = os.environ.get("GRAFANA_PREVIEW_URL", "")
    if url:
        lines += ["", f"[Open staging Grafana]({url})"]
    else:
        lines += ["", "Set the repository variable `GRAFANA_PREVIEW_URL` to add a staging link here."]
    server, repo, run = (os.environ.get(name) for name in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    if server and repo and run:
        lines += ["", f"[Workflow run]({server}/{repo}/actions/runs/{run})"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "publish", "report"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("state", type=Path)
    args = parser.parse_args()
    state = {}
    try:
        if args.command != "build" and args.state.exists():
            state = json.loads(args.state.read_text())
        if args.command == "report":
            print(report(state), end="")
            return 0
        pulls = selected_pulls(args.manifest)
        if args.command == "build":
            build(pulls, state)
        else:
            publish(pulls, state)
    except (OSError, ValueError, RuntimeError) as exc:
        state["error"] = str(exc)
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if args.command != "report":
            args.state.write_text(json.dumps(state, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
