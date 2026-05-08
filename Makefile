COMPOSE ?= docker compose

.PHONY: up down logs build restart test mcp-smoke shell

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

build:
	$(COMPOSE) build

restart:
	$(COMPOSE) restart

test:
	$(COMPOSE) run --rm mcp-gateway pytest -q

mcp-smoke:
	$(COMPOSE) run --rm mcp-gateway pytest -q tests/test_app.py -k mcp_discovery

shell:
	$(COMPOSE) exec mcp-gateway sh
