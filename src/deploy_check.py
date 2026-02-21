from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXIT_OK = 0
EXIT_DEPLOY_NOT_SUCCESS = 2
EXIT_TOOLING_ERROR = 3

ERROR_PATTERNS = [
    r"CREATE_FAILED",
    r"ROLLBACK",
    r"Error:",
    r"Not authorized",
    r"InvalidRequest",
    r"AccessDenied",
]


class DeployCheckError(RuntimeError):
    """Raised when local tooling cannot fetch deploy run/log data."""


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: int
    status: str
    conclusion: str | None
    html_url: str | None
    head_sha: str | None
    event: str | None


def parse_repo_from_remote(remote_url: str) -> str:
    raw = remote_url.strip()
    if raw.endswith(".git"):
        raw = raw[:-4]
    if raw.startswith("https://github.com/"):
        return raw[len("https://github.com/") :]
    if raw.startswith("http://github.com/"):
        return raw[len("http://github.com/") :]
    if raw.startswith("git@github.com:"):
        return raw[len("git@github.com:") :]
    raise DeployCheckError(f"Unsupported git remote URL format: {remote_url}")


def select_latest_run(
    runs: list[dict[str, Any]],
    *,
    allowed_events: tuple[str, ...] = ("push", "workflow_dispatch"),
) -> dict[str, Any] | None:
    for run in runs:
        if not isinstance(run, dict):
            continue
        event = str(run.get("event") or "")
        if event in allowed_events:
            return run
    return None


def extract_error_lines(log_text: str, *, max_lines: int = 40) -> list[str]:
    patterns = [re.compile(pattern, flags=re.IGNORECASE) for pattern in ERROR_PATTERNS]
    matched: list[str] = []
    for line in log_text.splitlines():
        if any(pattern.search(line) for pattern in patterns):
            matched.append(line)
            if len(matched) >= max_lines:
                break
    return matched


def tail_log(log_text: str, *, line_count: int) -> str:
    lines = log_text.splitlines()
    if line_count <= 0:
        return ""
    tail = lines[-line_count:]
    return "\n".join(tail)


def _run_cmd(args: list[str]) -> str:
    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise DeployCheckError(
            f"Command not found: {args[0]}. Install required tooling first."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise DeployCheckError(f"Command failed ({' '.join(args)}): {detail}") from exc
    return result.stdout


def _ensure_gh_available() -> None:
    _run_cmd(["gh", "--version"])
    # This exits non-zero when not authenticated.
    _run_cmd(["gh", "auth", "status"])


def _repo_from_git_origin() -> str:
    remote = _run_cmd(["git", "remote", "get-url", "origin"]).strip()
    return parse_repo_from_remote(remote)


def _load_latest_run(*, repo: str, workflow: str, branch: str) -> RunSummary:
    raw = _run_cmd(
        [
            "gh",
            "api",
            f"repos/{repo}/actions/workflows/{workflow}/runs?branch={branch}&per_page=30",
        ]
    )
    payload = json.loads(raw)
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
    latest = select_latest_run(runs if isinstance(runs, list) else [])
    if latest is None:
        raise DeployCheckError(
            f"No deploy workflow runs found for workflow={workflow} branch={branch}"
        )
    return RunSummary(
        run_id=int(latest["id"]),
        status=str(latest.get("status") or ""),
        conclusion=(str(latest["conclusion"]) if latest.get("conclusion") else None),
        html_url=(str(latest["html_url"]) if latest.get("html_url") else None),
        head_sha=(str(latest["head_sha"]) if latest.get("head_sha") else None),
        event=(str(latest["event"]) if latest.get("event") else None),
    )


def _load_run_by_id(*, repo: str, run_id: int) -> RunSummary:
    raw = _run_cmd(["gh", "api", f"repos/{repo}/actions/runs/{run_id}"])
    run = json.loads(raw)
    if not isinstance(run, dict):
        raise DeployCheckError(f"Unexpected run payload for run_id={run_id}")
    return RunSummary(
        run_id=int(run["id"]),
        status=str(run.get("status") or ""),
        conclusion=(str(run["conclusion"]) if run.get("conclusion") else None),
        html_url=(str(run["html_url"]) if run.get("html_url") else None),
        head_sha=(str(run["head_sha"]) if run.get("head_sha") else None),
        event=(str(run["event"]) if run.get("event") else None),
    )


def _download_artifact_log(
    *,
    repo: str,
    run_id: int,
    artifact_name_prefix: str,
) -> str | None:
    raw = _run_cmd(
        ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"]
    )
    payload = json.loads(raw)
    artifacts = payload.get("artifacts", []) if isinstance(payload, dict) else []
    if not isinstance(artifacts, list):
        return None

    artifact_name: str | None = None
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        name = str(artifact.get("name") or "")
        if name.startswith(artifact_name_prefix):
            artifact_name = name
            break
    if not artifact_name:
        return None

    with tempfile.TemporaryDirectory(prefix="mail-syncer-deploy-log-") as tmp_dir:
        _run_cmd(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "-n",
                artifact_name,
                "-D",
                tmp_dir,
            ]
        )
        candidates = sorted(Path(tmp_dir).rglob("deploy.log"))
        if not candidates:
            return None
        return candidates[0].read_text(encoding="utf-8", errors="replace")


def _fallback_run_log(*, run_id: int) -> str:
    return _run_cmd(["gh", "run", "view", str(run_id), "--log"])


def _print_summary(run: RunSummary) -> None:
    print(f"run_id: {run.run_id}")
    print(f"status: {run.status}")
    print(f"conclusion: {run.conclusion or 'none'}")
    print(f"event: {run.event or 'unknown'}")
    print(f"head_sha: {run.head_sha or 'unknown'}")
    print(f"url: {run.html_url or 'unknown'}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check latest deploy workflow run and summarize logs/errors"
    )
    parser.add_argument("--workflow", default="deploy.yml")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--tail-lines", type=int, default=120)
    parser.add_argument("--artifact-name-prefix", default="deploy-log-")
    parser.add_argument("--full-log", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _ensure_gh_available()
        repo = _repo_from_git_origin()
        run = (
            _load_run_by_id(repo=repo, run_id=args.run_id)
            if args.run_id
            else _load_latest_run(
                repo=repo,
                workflow=args.workflow,
                branch=args.branch,
            )
        )
        _print_summary(run)
        log_text = _download_artifact_log(
            repo=repo,
            run_id=run.run_id,
            artifact_name_prefix=args.artifact_name_prefix,
        )
        if not log_text:
            log_text = _fallback_run_log(run_id=run.run_id)
    except DeployCheckError as exc:
        print(f"tooling_error: {exc}")
        return EXIT_TOOLING_ERROR

    is_success = run.status == "completed" and run.conclusion == "success"
    if is_success:
        print("result: success")
        if args.full_log:
            print("\n--- full log ---")
            print(log_text)
        return EXIT_OK

    print("result: deploy_not_success")
    error_lines = extract_error_lines(log_text)
    if error_lines:
        print("\n--- detected error lines ---")
        for line in error_lines:
            print(line)
    print("\n--- log tail ---")
    print(tail_log(log_text, line_count=args.tail_lines))
    return EXIT_DEPLOY_NOT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
