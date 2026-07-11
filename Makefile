export PATH := $(HOME)/.local/bin:$(PATH)
CONDA_ENV := /Users/santosh_work/Work/Development/Environments/content_automation_env
PYTHON := $(CONDA_ENV)/bin/python

setup:
	conda create --prefix $(CONDA_ENV) python=3.11 -y
	$(PYTHON) -m pip install -r requirements.txt
	@echo "Now edit .env with your API keys (see README)."

video:
	$(PYTHON) -m pipeline.run

video-topic:
	$(PYTHON) -m pipeline.run --topic "$(TOPIC)"

plan:
	$(PYTHON) -m pipeline.plan

plan-topic:
	$(PYTHON) -m pipeline.plan --topic "$(TOPIC)"

eval:
	$(PYTHON) -m pipeline.evalharness

dashboard:
	$(PYTHON) -m uvicorn pipeline.ui.server:app --port 8420 --reload

# Dry-run by default (prints what WOULD post). Add --live + creds to actually publish:
#   make publish SLUG=2026-07-11-... ARGS=--live
publish:
	$(PYTHON) -m pipeline.publisher $(SLUG) $(ARGS)

.PHONY: setup video video-topic plan plan-topic eval dashboard publish
