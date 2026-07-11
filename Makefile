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

dashboard:
	$(PYTHON) -m uvicorn pipeline.ui.server:app --port 8420 --reload

.PHONY: setup video video-topic dashboard
