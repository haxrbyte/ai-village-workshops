# Twelve targets. `./setup.sh` is the front door; these are for afterwards.
-include .env
export

LAB_PORT ?= 8080
LAB_HOST ?= http://localhost:$(LAB_PORT)

.DEFAULT_GOAL := help

help:  ## show this
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

quickstart:  ## first run: check prereqs, pull, start, verify
	@./setup.sh

up:  ## start (already set up)
	@docker compose up -d

down:  ## stop
	@docker compose down

ps:  ## what is running
	@docker compose ps

logs:  ## follow logs (make logs S=victim)
	@docker compose logs -f $(S)

open:  ## open the lab in a browser
	@(command -v open >/dev/null && open "$(LAB_HOST)/start") || \
	 (command -v xdg-open >/dev/null && xdg-open "$(LAB_HOST)/start") || \
	 echo "$(LAB_HOST)/start"

check:  ## is the lab healthy? (gate 1 + gate 3)
	@bash scripts/smoke.sh "$(LAB_HOST)"
	@bash scripts/gate3_workshop2.sh "$(LAB_HOST)"

check-deep: check  ## ...plus exercises 5-6 and the network isolation claim
	@python3 scripts/gate5_6_automap.py --lab "$(LAB_HOST)"
	@printf "\n\033[1;36m==> Isolation\033[0m\n"
	 if docker compose exec -T victim python -c \
	   "import urllib.request; urllib.request.urlopen('http://1.1.1.1', timeout=4)" \
	   >/dev/null 2>&1; then \
	   printf "  \033[31mFAIL\033[0m  victim reached the internet — the sandbox network is not isolating\n"; exit 1; \
	 else \
	   printf "  \033[32mPASS\033[0m  victim cannot reach the internet\n"; \
	 fi

seed:  ## rebuild the fake hub's model repos
	@python3 scripts/seed_models.py

build:  ## rebuild the images (they are always built locally)
	@docker compose build

reset:  ## wipe uploads and team state, keep the stack up
	@docker compose run --rm --entrypoint sh -T listener \
	  -c 'rm -rf /data/uploads/* /data/tenants/* /data/hits.db*' 2>/dev/null || true
	@docker compose restart listener mailmate hub >/dev/null
	@echo "  state cleared"

nuke:  ## stop everything and delete all state
	@docker compose down -v
	@docker run --rm -v "$(PWD)/state:/s" alpine sh -c 'rm -rf /s/* /s/.[!.]*' 2>/dev/null || true
	@echo "  gone"

.PHONY: help quickstart up down ps logs open check check-deep seed build reset nuke
