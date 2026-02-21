.PHONY: install test lint run clean format check

install:
	pip install --break-system-packages -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/
	black --check src/

format:
	black src/
	ruff check --fix src/

run:
	python -m lmstudio_tui

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

check: lint test
