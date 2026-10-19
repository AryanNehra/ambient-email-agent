"""Metric functions checked against hand-computed examples."""

import math

from evals.judge_calibration.metrics import (
    accuracy,
    bootstrap_ci,
    cohen_kappa,
    confusion_matrix,
    false_fail_rate,
    false_pass_rate,
)


def test_cohen_kappa_hand_computed_example():
    # po = 3/4 = 0.75; pe = 0.5*0.25 + 0.5*0.75 = 0.5; kappa = (0.75-0.5)/0.5 = 0.5
    human = ["pass", "pass", "fail", "fail"]
    judge = ["pass", "fail", "fail", "fail"]
    assert cohen_kappa(human, judge) == 0.5


def test_cohen_kappa_perfect_agreement_is_one():
    assert cohen_kappa(["pass", "fail", "pass"], ["pass", "fail", "pass"]) == 1.0


def test_cohen_kappa_chance_agreement_near_zero():
    # Independent coin-flip-like labels with no skew: kappa should be ~0.
    human = ["pass", "fail", "pass", "fail"]
    judge = ["pass", "pass", "fail", "fail"]
    kappa = cohen_kappa(human, judge)
    # po = 2/4 = 0.5; pe = 0.5*0.5+0.5*0.5 = 0.5; kappa = 0
    assert kappa == 0.0


def test_accuracy_hand_computed():
    assert accuracy(["pass", "pass", "fail", "fail"], ["pass", "fail", "fail", "fail"]) == 0.75


def test_confusion_matrix_counts():
    cm = confusion_matrix(["pass", "pass", "fail"], ["pass", "fail", "fail"])
    assert cm[("pass", "pass")] == 1
    assert cm[("pass", "fail")] == 1
    assert cm[("fail", "fail")] == 1


def test_false_pass_rate_only_considers_human_fails():
    # human fails: indices 2,3 (judge: fail, fail) -> 0/2 false passes
    human = ["pass", "pass", "fail", "fail"]
    judge = ["pass", "fail", "fail", "fail"]
    assert false_pass_rate(human, judge) == 0.0


def test_false_fail_rate_only_considers_human_passes():
    # human passes: indices 0,1 (judge: pass, fail) -> 1/2 false fails
    human = ["pass", "pass", "fail", "fail"]
    judge = ["pass", "fail", "fail", "fail"]
    assert false_fail_rate(human, judge) == 0.5


def test_bootstrap_ci_contains_true_mean_for_constant_values():
    lower, upper = bootstrap_ci([1.0, 1.0, 1.0, 1.0], seed=0)
    assert lower == 1.0
    assert upper == 1.0


def test_bootstrap_ci_bounds_are_ordered_and_within_range():
    lower, upper = bootstrap_ci([0.0, 1.0, 1.0, 1.0, 0.0], seed=42)
    assert 0.0 <= lower <= upper <= 1.0


def test_empty_input_returns_nan():
    assert math.isnan(accuracy([], []))
    assert math.isnan(cohen_kappa([], []))
