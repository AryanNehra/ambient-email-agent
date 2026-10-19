"""Interactive CLI for collecting human labels on evals/judge_calibration/items.jsonl.

Usage:
    python -m evals.judge_calibration.label              # interactive labeling
    python -m evals.judge_calibration.label --csv-template  # (re)write labels.csv template
    python -m evals.judge_calibration.label --from-csv    # import labels.csv into human_labels.jsonl

At each item you'll see the email, the agent's response, and the rubric --
but not which quality tier we designed it as, so your label isn't anchored
by our intent. Commands: p[ass], f[ail], optionally followed by a 1-5 score
(e.g. "p 4"), s(kip), u(ndo, re-label the previous item), q(uit, saves progress).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path

HERE = Path(__file__).parent
ITEMS_PATH = HERE / "items.jsonl"
LABELS_PATH = HERE / "human_labels.jsonl"
CSV_TEMPLATE_PATH = HERE / "labels.csv"
ORDER_SEED = 20261019  # fixed so resuming a session keeps the same shuffled order


def _load_items() -> list[dict]:
    items = []
    with open(ITEMS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _load_existing_labels() -> dict[str, dict]:
    if not LABELS_PATH.exists():
        return {}
    labels = {}
    with open(LABELS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                labels[row["item_id"]] = row
    return labels


def _append_label(row: dict) -> None:
    with open(LABELS_PATH, "a") as f:
        f.write(json.dumps(row) + "\n")


def _rewrite_labels(labels_by_id: dict[str, dict]) -> None:
    with open(LABELS_PATH, "w") as f:
        for row in labels_by_id.values():
            f.write(json.dumps(row) + "\n")


def _render_item(item: dict, index: int, total: int) -> str:
    email = item["email"]
    return (
        f"\n--- Item {index}/{total} ({item['id']}) ---\n"
        f"From: {email['author']}\nTo: {email['to']}\nSubject: {email['subject']}\n\n"
        f"{email['email_thread']}\n"
        f"\n[Rubric criteria]\n{item['rubric_criteria']}\n"
        f"\n[Agent response]\n{item['agent_response']}\n"
    )


def write_csv_template(items: list[dict]) -> None:
    with open(CSV_TEMPLATE_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item_id", "label", "score_1_5", "notes"])
        for item in items:
            writer.writerow([item["id"], "", "", ""])
    print(f"Wrote template: {CSV_TEMPLATE_PATH}")


def import_from_csv() -> None:
    if not CSV_TEMPLATE_PATH.exists():
        print(f"No {CSV_TEMPLATE_PATH} found -- run --csv-template first.")
        return
    existing = _load_existing_labels()
    imported = 0
    with open(CSV_TEMPLATE_PATH) as f:
        for row in csv.DictReader(f):
            label = (row.get("label") or "").strip().lower()
            if label not in ("pass", "fail"):
                continue
            score_raw = (row.get("score_1_5") or "").strip()
            existing[row["item_id"]] = {
                "item_id": row["item_id"],
                "label": label,
                "score": int(score_raw) if score_raw else None,
                "notes": row.get("notes") or "",
                "timestamp": time.time(),
            }
            imported += 1
    _rewrite_labels(existing)
    print(f"Imported {imported} labels from {CSV_TEMPLATE_PATH} into {LABELS_PATH}")


def _parse_command(raw: str) -> tuple[str, int | None] | None:
    raw = raw.strip().lower()
    if not raw:
        return None
    parts = raw.split()
    head = parts[0]
    score = None
    if len(parts) > 1 and parts[1].isdigit():
        score = int(parts[1])
        if not (1 <= score <= 5):
            score = None
    if head in ("p", "pass"):
        return ("pass", score)
    if head in ("f", "fail"):
        return ("fail", score)
    if head in ("s", "skip"):
        return ("skip", None)
    if head in ("u", "undo"):
        return ("undo", None)
    if head in ("q", "quit"):
        return ("quit", None)
    return None


def run_interactive() -> None:
    items = _load_items()
    rng = random.Random(ORDER_SEED)
    order = list(range(len(items)))
    rng.shuffle(order)
    shuffled_items = [items[i] for i in order]

    labels_by_id = _load_existing_labels()
    already_done = len([i for i in shuffled_items if i["id"] in labels_by_id])
    print(
        f"{already_done}/{len(shuffled_items)} already labeled. "
        f"Commands: p[ass] [1-5], f[ail] [1-5], s(kip), u(ndo), q(uit)."
    )

    history: list[str] = []
    idx = 0
    while idx < len(shuffled_items):
        item = shuffled_items[idx]
        if item["id"] in labels_by_id:
            idx += 1
            continue

        print(_render_item(item, idx + 1, len(shuffled_items)))
        raw = input("Label> ")
        parsed = _parse_command(raw)
        if parsed is None:
            print("Didn't understand that -- try p, f, s, u, or q.")
            continue

        action, score = parsed
        if action == "quit":
            print(f"Saved progress: {len(labels_by_id)}/{len(shuffled_items)} labeled.")
            return
        if action == "skip":
            idx += 1
            continue
        if action == "undo":
            if history:
                last_id = history.pop()
                labels_by_id.pop(last_id, None)
                _rewrite_labels(labels_by_id)
                idx = max(idx - 1, 0)
                print(f"Undid label for {last_id}.")
            else:
                print("Nothing to undo yet.")
            continue

        row = {
            "item_id": item["id"],
            "label": action,
            "score": score,
            "notes": "",
            "timestamp": time.time(),
        }
        labels_by_id[item["id"]] = row
        _append_label(row)
        history.append(item["id"])
        idx += 1

    print(f"All {len(shuffled_items)} items labeled. Thank you!")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-template", action="store_true")
    parser.add_argument("--from-csv", action="store_true")
    args = parser.parse_args()

    if args.csv_template:
        write_csv_template(_load_items())
    elif args.from_csv:
        import_from_csv()
    else:
        run_interactive()


if __name__ == "__main__":
    main()
