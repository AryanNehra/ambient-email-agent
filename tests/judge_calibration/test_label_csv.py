"""Offline tests for the labeling CLI's CSV template + import roundtrip."""

import json

from evals.judge_calibration import label


def test_csv_template_and_import_roundtrip(tmp_path, monkeypatch):
    csv_path = tmp_path / "labels.csv"
    labels_path = tmp_path / "human_labels.jsonl"
    monkeypatch.setattr(label, "CSV_TEMPLATE_PATH", csv_path)
    monkeypatch.setattr(label, "LABELS_PATH", labels_path)

    items = [{"id": "X-1"}, {"id": "X-2"}]
    label.write_csv_template(items)
    assert csv_path.exists()

    # Fill in the template as a human would.
    csv_path.write_text("item_id,label,score_1_5,notes\nX-1,pass,4,looks good\nX-2,fail,2,wrong time\n")

    label.import_from_csv()

    rows = {json.loads(line)["item_id"]: json.loads(line) for line in labels_path.read_text().splitlines()}
    assert rows["X-1"]["label"] == "pass"
    assert rows["X-1"]["score"] == 4
    assert rows["X-2"]["label"] == "fail"


def test_import_from_csv_skips_unlabeled_rows(tmp_path, monkeypatch):
    csv_path = tmp_path / "labels.csv"
    labels_path = tmp_path / "human_labels.jsonl"
    monkeypatch.setattr(label, "CSV_TEMPLATE_PATH", csv_path)
    monkeypatch.setattr(label, "LABELS_PATH", labels_path)

    csv_path.write_text("item_id,label,score_1_5,notes\nX-1,,,\nX-2,pass,,\n")
    label.import_from_csv()

    rows = [json.loads(line) for line in labels_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["item_id"] == "X-2"


def test_parse_command_variants():
    assert label._parse_command("p") == ("pass", None)
    assert label._parse_command("pass 4") == ("pass", 4)
    assert label._parse_command("f 9") == ("fail", None)  # out-of-range score is dropped
    assert label._parse_command("s") == ("skip", None)
    assert label._parse_command("u") == ("undo", None)
    assert label._parse_command("q") == ("quit", None)
    assert label._parse_command("gibberish") is None
