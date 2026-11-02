"""The report of the model checks, and the guard rails on the job that holds the API key."""

from pathlib import Path

import yaml

from redteam.summary import render

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "model-checks.yml").read_text())
JOB = WORKFLOW["jobs"]["model"]


def test_a_part_that_did_not_finish_is_reported() -> None:
    text = render(None, None)
    assert "Evals: did not finish" in text and "Red team: did not finish" in text


def test_a_successful_attack_is_named() -> None:
    attacks = [
        {"id": "a", "threat": "T5", "verdict": "SUCCEEDED", "findings": ["leaked 'x'"]},
        {"id": "b", "threat": "T1", "verdict": "blocked", "findings": []},
    ]
    text = render(None, {"repeats": 3, "attacks": attacks})
    assert "1/2 attacks blocked" in text and "T5 `a` succeeded" in text and "`b`" not in text


def test_a_failed_case_is_listed_and_a_passing_one_is_not() -> None:
    cases = [
        {"case_id": "bad", "passed": 1, "repeats": 3, "misses": ["duration=30"]},
        {"case_id": "good", "passed": 3, "repeats": 3, "misses": []},
    ]
    evals = {
        "ok": False,
        "quality": 0.5,
        "threshold": 0.9,
        "failed_safety": [],
        "cost_usd": 0.05,
        "cases": cases,
    }
    text = render(evals, None)
    assert "Evals FAILED" in text and "`bad` 1/3" in text and "`good`" not in text


def test_t17_the_job_can_only_read_and_the_key_is_only_where_the_model_is_called() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert JOB["environment"] == "model-evals"
    with_key = [s["name"] for s in JOB["steps"] if "ANTHROPIC_API_KEY" in s.get("env", {})]
    assert with_key == ["Evals", "Red team"]
    assert "ANTHROPIC_API_KEY" not in JOB.get("env", {})


def test_t17_a_pull_request_from_a_fork_cannot_run_the_job() -> None:
    assert "head.repo.full_name == github.repository" in JOB["if"]
    # pull_request_target would hand a fork's code the secrets.
    assert "pull_request_target" not in WORKFLOW[True]  # YAML reads the key "on" as True
