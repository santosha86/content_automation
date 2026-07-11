export PATH := $(HOME)/.local/bin:$(PATH)

setup:
	uv sync
	cp -n .env.example .env || true
	@echo "Now edit .env with your API keys."

video:
	uv run python -m pipeline.run

video-topic:
	uv run python -m pipeline.run --topic "$(TOPIC)"

.PHONY: setup video video-topic
