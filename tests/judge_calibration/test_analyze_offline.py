"""Offline tests for the judge-calibration analysis pipeline: a fake judge,
and the "pending" gate that refuses to fabricate results when human labels
or a real API key are missing."""

import json

import pytest

from evals.judge_calibration import analyze
from evals.judge_calibration.judge import FakeJudge


def test_fake_judge_uses_registered_verdict():
    judge = FakeJudge(verdicts={"JC-01-good": "pass"})
    result = judge.grade_item_id("JC-01-good", agent_response="whatever", criteria="whatever")
    assert result.label == "pass"


def test_fake_judge_falls_back_to_heuristic_for_unregistered_id():
    judge = FakeJudge()
    result = judge.grade_item_id("unknown", agent_response="No action was taken.", criteria="n/a")
    assert result.label == "fail"


def test_majority_label_breaks_ties_toward_fail():
    assert analyze.majority_label(["pass", "fail"]) == "fail"
    assert analyze.majority_label(["pass", "pass", "fail"]) == "pass"
    assert analyze.majority_label(["fail", "fail", "fail"]) == "fail"


def test_self_consistency_all_agree_is_one():
    assert analyze.self_consistency(["pass", "pass", "pass"]) == 1.0


def test_self_consistency_partial_agreement():
    assert analyze.self_consistency(["pass", "pass", "fail"]) == pytest.approx(2 / 3)


def test_analyze_reports_pending_when_no_labels_exist(tmp_path, monkeypatch):
    items_path = tmp_path / "items.jsonl"
    items_path.write_text(json.dumps({"id": "X-1", "agent_response": "a", "rubric_criteria": "b"}) + "\n")
    labels_path = tmp_path / "human_labels.jsonl"  # does not exist
    results_dir = tmp_path / "results"

    monkeypatch.setattr(analyze, "ITEMS_PATH", items_path)
    monkeypatch.setattr(analyze, "LABELS_PATH", labels_path)
    monkeypatch.setattr(analyze, "RESULTS_DIR", results_dir)

    analyze.main()

    report = json.loads((results_dir / "judge_calibration.json").read_text())
    assert report["status"] == "pending"
    assert "label" in report["reason"]


def test_analyze_reports_pending_when_labels_incomplete(tmp_path, monkeypatch):
    items_path = tmp_path / "items.jsonl"
    items_path.write_text(
        json.dumps({"id": "X-1", "agent_response": "a", "rubric_criteria": "b"})
        + "\n"
        + json.dumps({"id": "X-2", "agent_response": "a", "rubric_criteria": "b"})
        + "\n"
    )
    labels_path = tmp_path / "human_labels.jsonl"
    labels_path.write_text(json.dumps({"item_id": "X-1", "label": "pass"}) + "\n")
    results_dir = tmp_path / "results"

    monkeypatch.setattr(analyze, "ITEMS_PATH", items_path)
    monkeypatch.setattr(analyze, "LABELS_PATH", labels_path)
    monkeypatch.setattr(analyze, "RESULTS_DIR", results_dir)

    analyze.main()

    report = json.loads((results_dir / "judge_calibration.json").read_text())
    assert report["status"] == "pending"
    assert "incomplete" in report["reason"]


def test_analyze_reports_pending_when_no_real_api_key(tmp_path, monkeypatch):
    items_path = tmp_path / "items.jsonl"
    items_path.write_text(json.dumps({"id": "X-1", "agent_response": "a", "rubric_criteria": "b"}) + "\n")
    labels_path = tmp_path / "human_labels.jsonl"
    labels_path.write_text(json.dumps({"item_id": "X-1", "label": "pass"}) + "\n")
    results_dir = tmp_path / "results"

    monkeypatch.setattr(analyze, "ITEMS_PATH", items_path)
    monkeypatch.setattr(analyze, "LABELS_PATH", labels_path)
    monkeypatch.setattr(analyze, "RESULTS_DIR", results_dir)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-placeholder-not-a-real-key")

    analyze.main()

    report = json.loads((results_dir / "judge_calibration.json").read_text())
    assert report["status"] == "pending"
    assert "OPENAI_API_KEY" in report["reason"]
