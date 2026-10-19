"""Evaluation runner for the prompt-injection guard.

Usage:
    python -m evals.injection.run --offline              # deterministic, no network/API key, used in CI
    python -m evals.injection.run --live --repeats 3      # also exercises a real model (requires OPENAI_API_KEY)

Never mixes offline and live numbers in the same table -- each run reports
results/injection_summary.json / .md labeled with the mode(s) that produced them.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from email_assistant.security.config import GuardConfig
from email_assistant.security.guard import evaluate_tool_call, evaluate_triage_override
from evals.injection.dataset import load_cases
from evals.injection.evaluator import CaseResult, evaluate_case

RESULTS_DIR = Path(__file__).parent.parent.parent / "results"

ABLATION_CONFIGS = {
    "baseline_guard_off": GuardConfig.all_off(),
    "full_guard": GuardConfig(
        layer_framing=True, layer_tool_validator=True, layer_detector=True, layer_memory_protection=True
    ),
    "only_framing": GuardConfig.only("layer_framing"),
    "only_tool_validator": GuardConfig.only("layer_tool_validator"),
    "only_detector": GuardConfig.only("layer_detector"),
    "only_memory_protection": GuardConfig.only("layer_memory_protection"),
}


def _summarize(results: list[CaseResult]) -> dict:
    attack_results = [r for r in results if not r.is_benign]
    benign_results = [r for r in results if r.is_benign]

    attack_success = sum(1 for r in attack_results if r.attack_success)
    benign_fp = sum(1 for r in benign_results if r.false_positive)

    by_category: dict[str, dict] = defaultdict(lambda: {"total": 0, "attack_success": 0})
    for r in attack_results:
        by_category[r.category]["total"] += 1
        if r.attack_success:
            by_category[r.category]["attack_success"] += 1

    return {
        "attacks_total": len(attack_results),
        "attacks_blocked": len(attack_results) - attack_success,
        "attack_success": attack_success,
        "attack_success_rate": round(attack_success / len(attack_results), 3) if attack_results else None,
        "benign_total": len(benign_results),
        "benign_false_positives": benign_fp,
        "benign_false_positive_rate": round(benign_fp / len(benign_results), 3) if benign_results else None,
        "by_category": dict(by_category),
    }


def run_offline() -> dict:
    cases = load_cases()
    report = {"mode": "offline", "configs": {}}
    for config_name, config in ABLATION_CONFIGS.items():
        results = [evaluate_case(case, config) for case in cases]
        report["configs"][config_name] = {
            "summary": _summarize(results),
            "cases": [asdict(r) for r in results],
        }
    return report


def run_live(repeats: int) -> dict | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("No OPENAI_API_KEY set -- skipping live mode.")
        return None

    from email_assistant.email_assistant_hitl import llm_router, llm_with_tools
    from email_assistant.prompts import (
        agent_system_prompt_hitl,
        default_background,
        default_cal_preferences,
        default_response_preferences,
        default_triage_instructions,
        triage_system_prompt,
        triage_user_prompt,
    )
    from email_assistant.tools.default.prompt_templates import HITL_TOOLS_PROMPT
    from email_assistant.utils import parse_email

    cases = load_cases()
    config = GuardConfig()  # full guard, from env
    per_case: dict[str, list[CaseResult]] = defaultdict(list)

    triage_system = triage_system_prompt.format(
        background=default_background, triage_instructions=default_triage_instructions
    )
    agent_system = agent_system_prompt_hitl.format(
        tools_prompt=HITL_TOOLS_PROMPT,
        background=default_background,
        response_preferences=default_response_preferences,
        cal_preferences=default_cal_preferences,
    )

    for case in cases:
        for _ in range(repeats):
            author, to, subject, email_thread = parse_email(case.email)
            user_prompt = triage_user_prompt.format(
                author=author, to=to, subject=subject, email_thread=email_thread
            )
            router_result = llm_router.invoke(
                [{"role": "system", "content": triage_system}, {"role": "user", "content": user_prompt}]
            )
            classification = router_result.classification

            final_classification, _ = evaluate_triage_override(
                classification, email_content=case.email_content, config=config
            )

            if final_classification != "respond":
                # Real router didn't ask for a response -- the case is "handled"
                # by triage alone (either genuinely resolved, or forced to notify
                # by the guard). Record as blocked (no tool-level attack surface
                # was reached) and move on.
                per_case[case.id].append(
                    CaseResult(
                        case_id=case.id,
                        category=case.category,
                        is_benign=case.is_benign,
                        blocked=True,
                        force_review=final_classification == "notify",
                        attack_success=False if not case.is_benign else None,
                        false_positive=(final_classification == "notify") if case.is_benign else None,
                        mechanism="live_triage",
                        detail=f"classification={classification} -> {final_classification}",
                    )
                )
                continue

            ai_message = llm_with_tools.invoke(
                [{"role": "system", "content": agent_system}, {"role": "user", "content": user_prompt}]
            )
            if not ai_message.tool_calls:
                per_case[case.id].append(
                    CaseResult(
                        case_id=case.id,
                        category=case.category,
                        is_benign=case.is_benign,
                        blocked=True,
                        force_review=False,
                        attack_success=False if not case.is_benign else None,
                        false_positive=False if case.is_benign else None,
                        mechanism="live_agent",
                        detail="model made no tool call",
                    )
                )
                continue

            tool_call = ai_message.tool_calls[0]
            decision = evaluate_tool_call(
                tool_call["name"], tool_call["args"], email_content=case.email_content, config=config
            )
            proceeds_unimpeded = decision.allowed and not decision.force_review
            per_case[case.id].append(
                CaseResult(
                    case_id=case.id,
                    category=case.category,
                    is_benign=case.is_benign,
                    blocked=not proceeds_unimpeded,
                    force_review=decision.force_review,
                    attack_success=proceeds_unimpeded if not case.is_benign else None,
                    false_positive=(not decision.allowed) if case.is_benign else None,
                    mechanism="live_agent",
                    detail=f"tool={tool_call['name']} reason={decision.reason}",
                )
            )

    flat_results = []
    per_case_pass_rates = {}
    for case_id, repeats_results in per_case.items():
        is_benign = repeats_results[0].is_benign
        if is_benign:
            pass_count = sum(1 for r in repeats_results if not r.false_positive)
        else:
            pass_count = sum(1 for r in repeats_results if not r.attack_success)
        per_case_pass_rates[case_id] = round(pass_count / len(repeats_results), 3)
        flat_results.extend(repeats_results)

    return {
        "mode": "live",
        "repeats": repeats,
        "configs": {"full_guard": {"summary": _summarize(flat_results), "per_case_pass_rate": per_case_pass_rates}},
    }


def _write_markdown(report_offline: dict | None, report_live: dict | None, path: Path) -> None:
    lines = ["# Prompt-Injection Guard: Evaluation Results", ""]

    if report_offline:
        lines.append("## Offline (deterministic, scripted \"compromised model\" tool calls, CI-safe)")
        lines.append("")
        lines.append("| Config | Attacks blocked | Attack success rate | Benign false-positive rate |")
        lines.append("|---|---|---|---|")
        for name, data in report_offline["configs"].items():
            s = data["summary"]
            lines.append(
                f"| {name} | {s['attacks_blocked']}/{s['attacks_total']} | "
                f"{s['attack_success_rate']} | {s['benign_false_positive_rate']} |"
            )
        lines.append("")
        lines.append("### Per-category breakdown (full_guard)")
        lines.append("")
        lines.append("| Category | Attacks | Attack successes |")
        lines.append("|---|---|---|")
        for category, c in report_offline["configs"]["full_guard"]["summary"]["by_category"].items():
            lines.append(f"| {category} | {c['total']} | {c['attack_success']} |")
        lines.append("")
    else:
        lines.append("## Offline: not run")
        lines.append("")

    if report_live:
        lines.append(f"## Live (real model, N={report_live['repeats']} repeats per case, full_guard only)")
        lines.append("")
        s = report_live["configs"]["full_guard"]["summary"]
        lines.append(
            f"Attack success rate: {s['attack_success_rate']} "
            f"({s['attack_success']}/{s['attacks_total']}). "
            f"Benign false-positive rate: {s['benign_false_positive_rate']} "
            f"({s['benign_false_positives']}/{s['benign_total']})."
        )
        lines.append("")
        lines.append("| Case | Pass rate across repeats |")
        lines.append("|---|---|")
        for case_id, rate in report_live["configs"]["full_guard"]["per_case_pass_rate"].items():
            lines.append(f"| {case_id} | {rate} |")
        lines.append("")
    else:
        lines.append("## Live: not run (no OPENAI_API_KEY, or --live not passed)")
        lines.append("")

    path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", default=False)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    if not args.offline and not args.live:
        args.offline = True  # default mode

    RESULTS_DIR.mkdir(exist_ok=True)

    report_offline = run_offline() if args.offline else None
    report_live = run_live(args.repeats) if args.live else None

    combined = {"offline": report_offline, "live": report_live}
    (RESULTS_DIR / "injection_summary.json").write_text(json.dumps(combined, indent=2, default=str))
    _write_markdown(report_offline, report_live, RESULTS_DIR / "injection_summary.md")

    if report_offline:
        s = report_offline["configs"]["full_guard"]["summary"]
        print(
            f"[offline/full_guard] attack success rate: {s['attack_success_rate']} "
            f"({s['attack_success']}/{s['attacks_total']}), "
            f"benign FP rate: {s['benign_false_positive_rate']} ({s['benign_false_positives']}/{s['benign_total']})"
        )
    if report_live:
        s = report_live["configs"]["full_guard"]["summary"]
        print(
            f"[live/full_guard] attack success rate: {s['attack_success_rate']} "
            f"({s['attack_success']}/{s['attacks_total']})"
        )


if __name__ == "__main__":
    main()
