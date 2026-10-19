"""Analyze how well the course's LLM-as-judge agrees with human labels.

Usage:
    python -m evals.judge_calibration.analyze

Requires evals/judge_calibration/human_labels.jsonl to exist and cover every
item in items.jsonl (collected via `python -m evals.judge_calibration.label`),
and OPENAI_API_KEY to run the real judge. If either is missing, this writes a
results file explicitly marked "pending" with an explanation, rather than
estimating or inventing numbers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import correlation

from evals.judge_calibration.judge import (
    RESPONSE_CRITERIA_SYSTEM_PROMPT,
    RESPONSE_CRITERIA_SYSTEM_PROMPT_PARAPHRASED,
    CriteriaGradeJudge,
)
from evals.judge_calibration.metrics import (
    bootstrap_ci,
    cohen_kappa,
    confusion_matrix,
    false_fail_rate,
    false_pass_rate,
)

HERE = Path(__file__).parent
ITEMS_PATH = HERE / "items.jsonl"
LABELS_PATH = HERE / "human_labels.jsonl"
RESULTS_DIR = HERE.parent.parent / "results"
N_REPEATS = 3


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_pending(reason: str) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {"status": "pending", "reason": reason}
    (RESULTS_DIR / "judge_calibration.json").write_text(json.dumps(payload, indent=2))
    (RESULTS_DIR / "judge_calibration.md").write_text(
        f"# LLM-Judge Calibration: Results\n\n**Status: pending.**\n\n{reason}\n"
    )
    print(f"judge_calibration: pending -- {reason}")


def majority_label(labels: list[str]) -> str:
    """Majority vote across repeats; ties break toward 'fail' (conservative)."""
    pass_count = sum(1 for label in labels if label == "pass")
    return "pass" if pass_count > len(labels) / 2 else "fail"


def self_consistency(labels: list[str]) -> float:
    """Fraction of repeats agreeing with the majority label."""
    majority = majority_label(labels)
    return sum(1 for label in labels if label == majority) / len(labels)


def main() -> None:
    if not ITEMS_PATH.exists():
        _write_pending("items.jsonl not found.")
        return
    items = _load_jsonl(ITEMS_PATH)
    items_by_id = {i["id"]: i for i in items}

    if not LABELS_PATH.exists():
        _write_pending(
            "No human labels yet. Run `python -m evals.judge_calibration.label` "
            "(about 20-30 minutes) and re-run this script after."
        )
        return

    labels = _load_jsonl(LABELS_PATH)
    labels_by_id = {row["item_id"]: row for row in labels}
    missing = [i for i in items_by_id if i not in labels_by_id]
    if missing:
        _write_pending(
            f"Human labels incomplete: {len(missing)}/{len(items_by_id)} items not yet labeled "
            f"({', '.join(sorted(missing)[:5])}{'...' if len(missing) > 5 else ''}). "
            "Run `python -m evals.judge_calibration.label` to finish, then re-run this script."
        )
        return

    if not os.environ.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"].startswith("sk-test"):
        _write_pending(
            "Human labels are complete, but no real OPENAI_API_KEY is set, so the live judge "
            "run (required to compute agreement) was not performed."
        )
        return

    judge = CriteriaGradeJudge(system_prompt=RESPONSE_CRITERIA_SYSTEM_PROMPT)
    paraphrased_judge = CriteriaGradeJudge(system_prompt=RESPONSE_CRITERIA_SYSTEM_PROMPT_PARAPHRASED)

    human_label_list = []
    judge_label_list = []
    per_item = []
    for item_id, item in items_by_id.items():
        human_label = labels_by_id[item_id]["label"]
        repeats = [
            judge.grade(agent_response=item["agent_response"], criteria=item["rubric_criteria"]).label
            for _ in range(N_REPEATS)
        ]
        final_label = majority_label(repeats)
        paraphrase_label = paraphrased_judge.grade(
            agent_response=item["agent_response"], criteria=item["rubric_criteria"]
        ).label

        human_label_list.append(human_label)
        judge_label_list.append(final_label)
        per_item.append(
            {
                "item_id": item_id,
                "human_label": human_label,
                "judge_repeats": repeats,
                "judge_majority_label": final_label,
                "judge_self_consistency": self_consistency(repeats),
                "judge_paraphrased_label": paraphrase_label,
                "response_length_chars": len(item["agent_response"]),
            }
        )

    kappa = cohen_kappa(human_label_list, judge_label_list)
    cm = confusion_matrix(human_label_list, judge_label_list)
    acc_values = [1.0 if h == j else 0.0 for h, j in zip(human_label_list, judge_label_list)]
    accuracy = sum(acc_values) / len(acc_values)
    ci_lower, ci_upper = bootstrap_ci(acc_values)

    avg_self_consistency = sum(r["judge_self_consistency"] for r in per_item) / len(per_item)
    paraphrase_agreement = sum(
        1 for r in per_item if r["judge_majority_label"] == r["judge_paraphrased_label"]
    ) / len(per_item)

    # Verbosity bias: among items the human marked "fail", does a longer response make the
    # judge more likely to pass it anyway? (Correlation needs >=2 points with nonzero variance.)
    fail_items = [r for r in per_item if r["human_label"] == "fail"]
    verbosity_bias = None
    if len(fail_items) >= 2:
        lengths = [r["response_length_chars"] for r in fail_items]
        judge_passed = [1.0 if r["judge_majority_label"] == "pass" else 0.0 for r in fail_items]
        if len(set(lengths)) > 1 and len(set(judge_passed)) > 1:
            verbosity_bias = correlation(lengths, judge_passed)

    report = {
        "status": "complete",
        "n_items": len(items_by_id),
        "n_repeats": N_REPEATS,
        "accuracy_vs_human": round(accuracy, 3),
        "accuracy_95ci": [round(ci_lower, 3), round(ci_upper, 3)],
        "cohen_kappa": round(kappa, 3),
        "confusion_matrix": {f"human={h},judge={j}": n for (h, j), n in cm.items()},
        "false_pass_rate": round(false_pass_rate(human_label_list, judge_label_list), 3),
        "false_fail_rate": round(false_fail_rate(human_label_list, judge_label_list), 3),
        "judge_self_consistency_avg": round(avg_self_consistency, 3),
        "rubric_paraphrase_agreement": round(paraphrase_agreement, 3),
        "verbosity_bias_correlation_on_human_fails": (
            round(verbosity_bias, 3) if verbosity_bias is not None else None
        ),
        "position_bias": "not applicable -- this judge grades a single response against a rubric, no pairwise comparison mode exists",
        "caveat": "n=30 is a small sample; treat point estimates with the 95% CI in mind, not as exact values.",
        "per_item": per_item,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "judge_calibration.json").write_text(json.dumps(report, indent=2))
    _write_markdown(report)
    print(
        f"accuracy={report['accuracy_vs_human']} (95% CI {report['accuracy_95ci']}), "
        f"kappa={report['cohen_kappa']}, self_consistency={report['judge_self_consistency_avg']}"
    )


def _write_markdown(report: dict) -> None:
    lines = [
        "# LLM-Judge Calibration: Results",
        "",
        f"n={report['n_items']} items, N={report['n_repeats']} judge repeats per item. {report['caveat']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy vs. human | {report['accuracy_vs_human']} (95% CI {report['accuracy_95ci']}) |",
        f"| Cohen's kappa | {report['cohen_kappa']} |",
        f"| False-pass rate | {report['false_pass_rate']} |",
        f"| False-fail rate | {report['false_fail_rate']} |",
        f"| Judge self-consistency (N={report['n_repeats']} repeats) | {report['judge_self_consistency_avg']} |",
        f"| Agreement under paraphrased rubric wording | {report['rubric_paraphrase_agreement']} |",
        f"| Verbosity bias (correlation, human-fail items only) | {report['verbosity_bias_correlation_on_human_fails']} |",
        f"| Position bias | {report['position_bias']} |",
        "",
        "## Confusion matrix",
        "",
    ]
    for key, count in report["confusion_matrix"].items():
        lines.append(f"- {key}: {count}")
    (RESULTS_DIR / "judge_calibration.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
