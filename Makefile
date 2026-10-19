.PHONY: install lint test eval-injection eval-calibration eval-all

install:
	pip install -e ".[dev]"

lint:
	ruff check src evals tests

test:
	pytest tests evals -q -m "not live"

eval-injection:
	python -m evals.injection.run --offline

eval-calibration:
	python -m evals.judge_calibration.analyze

eval-all: eval-injection eval-calibration
