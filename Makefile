.PHONY: install lint test eval-injection eval-calibration eval-all

install:
	pip install -e ".[dev]"

lint:
	# Scoped to our original code; the inherited course code under src/email_assistant
	# (minus security/) has its own pre-existing lint debt we don't own (see NOTICE.md).
	ruff check src/email_assistant/security evals tests/security

test:
	# Our offline test suite (tests/security, evals/*). The inherited course tests
	# under tests/test_response.py etc. need a real OpenAI + LangSmith key and are
	# run separately via `python tests/run_all_tests.py` (see README).
	pytest tests/security evals -q

eval-injection:
	python -m evals.injection.run --offline

eval-calibration:
	python -m evals.judge_calibration.analyze

eval-all: eval-injection eval-calibration
