VENV := .venv
ifeq ($(OS),Windows_NT)
PYTHON := $(VENV)/Scripts/python.exe
PIP := $(VENV)/Scripts/pip.exe
else
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
endif

.PHONY: venv install lint test check dev scheduler

venv:
	@if [ ! -x "$(PYTHON)" ]; then python -m venv $(VENV); fi
	$(PYTHON) -m pip install --upgrade pip setuptools wheel

install: venv
	$(PIP) install -r requirements-dev.txt
	$(PIP) check

lint: install
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .
	$(PYTHON) -m mypy inkdisplay

test: install
	$(PYTHON) -m pytest

check: lint test

dev: install
	$(PYTHON) run.py

scheduler: install
	$(PYTHON) run_scheduler.py