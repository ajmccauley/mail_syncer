from __future__ import annotations

from src.deploy_check import (
    extract_error_lines,
    parse_repo_from_remote,
    select_latest_run,
    tail_log,
)


def test_parse_repo_from_remote_https_and_ssh() -> None:
    assert (
        parse_repo_from_remote("https://github.com/ajmccauley/mail_syncer.git")
        == "ajmccauley/mail_syncer"
    )
    assert (
        parse_repo_from_remote("git@github.com:ajmccauley/mail_syncer.git")
        == "ajmccauley/mail_syncer"
    )


def test_select_latest_run_filters_supported_events() -> None:
    runs = [
        {"id": 100, "event": "pull_request"},
        {"id": 101, "event": "push"},
        {"id": 102, "event": "workflow_dispatch"},
    ]
    selected = select_latest_run(runs)
    assert selected is not None
    assert selected["id"] == 101


def test_extract_error_lines_matches_expected_patterns() -> None:
    log = "\n".join(
        [
            "step one ok",
            "CREATE_FAILED AWS::Lambda::Function MailSyncerFunction",
            "Error: Process completed with exit code 1.",
            "another info line",
        ]
    )
    lines = extract_error_lines(log)
    assert len(lines) == 2
    assert "CREATE_FAILED" in lines[0]
    assert "Error:" in lines[1]


def test_tail_log_returns_last_n_lines() -> None:
    log = "\n".join([f"line-{i}" for i in range(1, 8)])
    tail = tail_log(log, line_count=3)
    assert tail == "line-5\nline-6\nline-7"
