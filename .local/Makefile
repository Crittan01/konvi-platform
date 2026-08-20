SHELL := /bin/bash

MAKEFILE_DIR := $(abspath $(dir $(realpath $(firstword $(MAKEFILE_LIST)))))
REPO      ?= $(abspath $(MAKEFILE_DIR)/..)
STATE_DIR ?= $(MAKEFILE_DIR)
LOG_DIR   := $(STATE_DIR)/logs
PID_DIR   := $(STATE_DIR)/pids

# Variables ngrok leídas desde .env.local del repo (SOLO estas — ver nota):
#   NGROK_AUTHTOKEN / NGROK_DOMAIN_API         → API (8001)
#   NGROK_AUTHTOKEN_CONNECTOR / NGROK_DOMAIN_CONNECTOR → Connector (8000)
#
# S7 (2026-08-16) — HOMOLOGACIÓN STG↔PRD: ya NO se hace `-include .env.local`
# global + export (el "megáfono": todo servicio veía todas las vars; en PRD cada
# servicio Render recibe SOLO las suyas). Ahora cada start-* genera un env
# FILTRADO por servicio con scripts/dev_env_for_service.py (fail-closed: si
# falta una var que el servicio tiene en PRD, el arranque aborta) y lo lanza con
# entorno limpio (env -i). El megáfono queda solo para las 4 vars NGROK de los
# túneles, que no son de runtime de servicios.
NGROK_AUTHTOKEN           := $(shell grep -s '^NGROK_AUTHTOKEN='           $(REPO)/.env.local | cut -d= -f2-)
NGROK_DOMAIN_API          := $(shell grep -s '^NGROK_DOMAIN_API='          $(REPO)/.env.local | cut -d= -f2-)
NGROK_AUTHTOKEN_CONNECTOR := $(shell grep -s '^NGROK_AUTHTOKEN_CONNECTOR=' $(REPO)/.env.local | cut -d= -f2-)
NGROK_DOMAIN_CONNECTOR    := $(shell grep -s '^NGROK_DOMAIN_CONNECTOR='    $(REPO)/.env.local | cut -d= -f2-)

ENV_DIR := $(STATE_DIR)/env
# Entorno limpio preservando solo lo de plataforma (PATH incluye nvm/pnpm del
# shell que invoca make; HOME para caches de node/python).
CLEAN_ENV := env -i PATH="$(PATH)" HOME="$(HOME)" LANG="$(LANG)"

.PHONY: help up down restart status logs print-urls clean db \
        start-api start-connector start-orchestrator start-web \
        stop-api  stop-connector  stop-orchestrator  stop-web  \
        _preflight-db _tunnel-api _tunnel-connector _tunnel-down

# ── Ayuda ─────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "Konvi — entorno local (STG homologado a PRD — S7)"
	@echo ""
	@echo "  make up           Inicia servicios + túneles ngrok (NO la DB — ver make db)"
	@echo "  make db           Levanta la DB: Supabase local en podman (supabase start)"
	@echo "  make down         Detiene todo (no toca la DB)"
	@echo "  make restart      down + up"
	@echo "  make status       Estado de todos los procesos"
	@echo "  make print-urls   URLs para configurar en Meta / Wompi / MeLi"
	@echo "  make logs SERVICE=<svc>"
	@echo "                    Tail de logs en tiempo real"
	@echo "                    Servicios: web | api | connector | orchestrator"
	@echo "                               ngrok-api | ngrok-connector"
	@echo ""
	@echo "  Servicios individuales (para debug):"
	@echo "  make start-api / stop-api            (:8001, uvicorn main:app — = PRD)"
	@echo "  make start-connector / stop-connector(:8000, uvicorn main:app — = PRD)"
	@echo "  make start-orchestrator / stop-orchestrator(:8002, uvicorn server:app — = PRD)"
	@echo "  make start-web / stop-web            (:3000, next dev — desarrollo diario)"
	@echo "  make start-web-prod                  (:3000, next start — modo de PRD; lo usa la certificación)"
	@echo ""
	@echo "  Homologación (S7): cada servicio recibe SOLO las env vars que su"
	@echo "  contraparte Render recibe en PRD (filtro fail-closed:"
	@echo "  scripts/dev_env_for_service.py → .local/env/<svc>.env, entorno limpio)."
	@echo "  Certificación: bash scripts/certify_stg.sh"
	@echo ""
	@echo "  make clean        Elimina logs y PIDs"
	@echo ""

# ── Checks internos ───────────────────────────────────────────────────────────

_check:
	@[ -d "$(REPO)" ]                     || (echo "ERROR: REPO no existe: $(REPO)" && exit 1)
	@[ -f "$(REPO)/.env.local" ]                || (echo "ERROR: falta $(REPO)/.env.local" && exit 1)
	@[ -f "$(REPO)/apps/web/.env.local" ] || (echo "ERROR: falta apps/web/.env.local" && exit 1)
	@command -v pnpm       >/dev/null     || (echo "ERROR: pnpm no encontrado" && exit 1)
	@command -v python3.11 >/dev/null     || (echo "ERROR: python3.11 no encontrado" && exit 1)
	@command -v ngrok      >/dev/null     || (echo "ERROR: ngrok no encontrado" && exit 1)
	@mkdir -p "$(LOG_DIR)" "$(PID_DIR)" "$(ENV_DIR)"

# ── DB local (NO la levanta `up` — pieza separada del stack) ─────────────────

db:
	@export DOCKER_HOST="unix:///run/user/$$(id -u)/podman/podman.sock"; \
	supabase start 2>&1 | tail -3; \
	if ! curl -fsS --max-time 3 -o /dev/null http://127.0.0.1:54321/rest/v1/ 2>/dev/null; then \
		echo "  db: estado stale de contenedores (la CLI cree que corre pero el contenedor"; \
		echo "      postgres está exited — pasa tras suspensión/reinicio de la VM)."; \
		echo "      Recuperando con stop+start…"; \
		supabase stop >/dev/null 2>&1; supabase start 2>&1 | tail -3; \
	fi; \
	curl -fsS --max-time 3 -o /dev/null http://127.0.0.1:54321/rest/v1/ 2>/dev/null \
		&& echo "  db: Supabase local OK (127.0.0.1:54321)" \
		|| { echo "  ERROR: la DB sigue sin responder — revisar: supabase status"; exit 1; }

# Preflight de DB para `up`: los servicios arrancan y se recuperan solos cuando
# la DB vuelve, pero arrancar sin DB deja todo lo que toca datos roto (503 en
# /health/ready) — advertir fuerte en vez de fallar en silencio.
_preflight-db:
	@curl -fsS --max-time 3 -o /dev/null http://127.0.0.1:54321/rest/v1/ 2>/dev/null \
		&& echo "  db: Supabase local OK (127.0.0.1:54321)" \
		|| { echo ""; \
		     echo "  ⚠️  DB local NO responde (127.0.0.1:54321)."; \
		     echo "     Los servicios arrancan, pero todo lo que toca DB fallará hasta"; \
		     echo "     que la levantes:  make db   (= supabase start en podman)"; echo ""; }

# ── Stack completo ────────────────────────────────────────────────────────────

up: _check _preflight-db start-api start-connector start-orchestrator start-web _tunnel-api _tunnel-connector
	@echo ""
	@$(MAKE) -C $(STATE_DIR) print-urls

down: stop-web stop-api stop-connector stop-orchestrator _tunnel-down
	@echo "Stack detenido."

restart: down up

# ── Estado y logs ─────────────────────────────────────────────────────────────

status:
	@echo ""
	@for svc in web api connector orchestrator ngrok-api ngrok-connector; do \
		pidfile="$(PID_DIR)/$$svc.pid"; \
		if [ -f "$$pidfile" ] && kill -0 $$(cat "$$pidfile") 2>/dev/null; then \
			echo "  $$svc: RUNNING  (PID $$(cat $$pidfile))"; \
		else \
			echo "  $$svc: STOPPED"; \
			rm -f "$$pidfile"; \
		fi; \
	done
	@curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:54321/rest/v1/ 2>/dev/null \
		&& echo "  db (supabase local): UP" \
		|| echo "  db (supabase local): DOWN — levantarla con: make db"
	@echo ""

logs:
	@[ -n "$(SERVICE)" ] || (echo "Uso: make logs SERVICE=<api|connector|web|orchestrator|ngrok-api|ngrok-connector>" && exit 1)
	@[ -f "$(LOG_DIR)/$(SERVICE).log" ] || (echo "Log no encontrado: $(LOG_DIR)/$(SERVICE).log" && exit 1)
	@tail -n 80 -f "$(LOG_DIR)/$(SERVICE).log"

print-urls:
	@json4040=$$(curl -fsS --max-time 2 http://127.0.0.1:4040/api/tunnels 2>/dev/null || echo '{"tunnels":[]}'); \
	json4041=$$(curl -fsS --max-time 2 http://127.0.0.1:4041/api/tunnels 2>/dev/null || echo '{"tunnels":[]}'); \
	json=$$(python3 -c "import json; a=json.loads(r'''$$json4040''').get('tunnels',[]); b=json.loads(r'''$$json4041''').get('tunnels',[]); print(json.dumps({'tunnels':a+b}))"); \
	api_url=$$(echo "$$json" | jq -r '.tunnels[]? | select(.config.addr|test(":8001$$")) | .public_url' | head -1); \
	con_url=$$(echo "$$json" | jq -r '.tunnels[]? | select(.config.addr|test(":8000$$")) | .public_url' | head -1); \
	echo ""; \
	echo "=== URLs activas ==="; \
	printf "  %-16s %s\n" "API (8001):"       "$${api_url:-OFFLINE}"; \
	printf "  %-16s %s\n" "CONNECTOR (8000):" "$${con_url:-OFFLINE}"; \
	echo ""; \
	if [ -n "$$api_url" ] && [ "$$api_url" != "null" ]; then \
		echo "Wompi — Dashboard → Eventos → URL de eventos:"; \
		echo "  $$api_url/api/v1/webhooks/wompi"; \
		echo ""; \
		echo "Mercado Libre — DevCenter → Tu App:"; \
		echo "  Redirect URI:    $$api_url/api/v1/integrations/meli/callback"; \
		echo "  Notificaciones:  $$api_url/api/v1/meli/webhook"; \
	else \
		echo "  [API offline]"; \
	fi; \
	echo ""; \
	if [ -n "$$con_url" ] && [ "$$con_url" != "null" ]; then \
		echo "Meta WhatsApp — Facebook Developers → Webhooks:"; \
		echo "  Callback URL:  $$con_url/api/v1/whatsapp/webhook/d0000000-0000-0000-0000-000000000001"; \
		echo "  (el tenant_id del PATH es obligatorio — tenant sandbox STG; verify token per-tenant,"; \
		echo "   configurado en tenant_integrations del STG, NO en .env)"; \
	else \
		echo "  [Connector offline]"; \
	fi
	@echo ""

# ── Start servicios ───────────────────────────────────────────────────────────

start-web: _check
	@if [ -f "$(PID_DIR)/web.pid" ] && kill -0 $$(cat "$(PID_DIR)/web.pid") 2>/dev/null; then \
		echo "  web: ya corriendo"; \
	else \
		rm -f "$(PID_DIR)/web.pid"; \
		python3.11 "$(REPO)/scripts/dev_env_for_service.py" web --out "$(ENV_DIR)/web.env" || exit 1; \
		nohup $(CLEAN_ENV) bash -c 'cd "$(REPO)" && set -a && source "$(ENV_DIR)/web.env" && set +a && PORT=3000 exec pnpm --filter web dev' \
			> "$(LOG_DIR)/web.log" 2>&1 & echo $$! > "$(PID_DIR)/web.pid"; \
		sleep 1; \
		kill -0 $$(cat "$(PID_DIR)/web.pid") 2>/dev/null \
			&& echo "  web: iniciado  → http://localhost:3000" \
			|| { echo "  ERROR web. Ver: $(LOG_DIR)/web.log"; tail -n 20 "$(LOG_DIR)/web.log"; rm -f "$(PID_DIR)/web.pid"; exit 1; }; \
	fi

# start-web-prod: web en modo PRODUCCIÓN (next build && next start) — el modo
# que corre PRD (render.yaml: pnpm run start). Lo usa la certificación de
# homologación (scripts/certify_stg.sh); para desarrollo diario usa start-web.
start-web-prod: _check
	@$(MAKE) -C $(STATE_DIR) stop-web
	@python3.11 "$(REPO)/scripts/dev_env_for_service.py" web --out "$(ENV_DIR)/web.env" || exit 1
	@rm -f "$(PID_DIR)/web.pid"
	@nohup $(CLEAN_ENV) bash -c 'cd "$(REPO)" && set -a && source "$(ENV_DIR)/web.env" && set +a && PORT=3000 exec pnpm --filter web start' \
		> "$(LOG_DIR)/web.log" 2>&1 & echo $$! > "$(PID_DIR)/web.pid"
	@sleep 2; kill -0 $$(cat "$(PID_DIR)/web.pid") 2>/dev/null \
		&& echo "  web(PROD): iniciado → http://localhost:3000" \
		|| { echo "  ERROR web(PROD). Ver: $(LOG_DIR)/web.log"; tail -n 20 "$(LOG_DIR)/web.log"; rm -f "$(PID_DIR)/web.pid"; exit 1; }

start-api: _check
	@if [ -f "$(PID_DIR)/api.pid" ] && kill -0 $$(cat "$(PID_DIR)/api.pid") 2>/dev/null; then \
		echo "  api: ya corriendo"; \
	else \
		rm -f "$(PID_DIR)/api.pid"; \
		python3.11 "$(REPO)/scripts/dev_env_for_service.py" api --out "$(ENV_DIR)/api.env" || exit 1; \
		nohup $(CLEAN_ENV) bash -c 'cd "$(REPO)/services/api" && set -a && source "$(ENV_DIR)/api.env" && set +a && exec uvicorn main:app --host 0.0.0.0 --port 8001' \
			> "$(LOG_DIR)/api.log" 2>&1 & echo $$! > "$(PID_DIR)/api.pid"; \
		sleep 1; \
		kill -0 $$(cat "$(PID_DIR)/api.pid") 2>/dev/null \
			&& echo "  api: iniciado  → http://localhost:8001" \
			|| { echo "  ERROR api. Ver: $(LOG_DIR)/api.log"; tail -n 20 "$(LOG_DIR)/api.log"; rm -f "$(PID_DIR)/api.pid"; exit 1; }; \
	fi

start-connector: _check
	@if [ -f "$(PID_DIR)/connector.pid" ] && kill -0 $$(cat "$(PID_DIR)/connector.pid") 2>/dev/null; then \
		echo "  connector: ya corriendo"; \
	else \
		rm -f "$(PID_DIR)/connector.pid"; \
		python3.11 "$(REPO)/scripts/dev_env_for_service.py" connector --out "$(ENV_DIR)/connector.env" || exit 1; \
		nohup $(CLEAN_ENV) bash -c 'cd "$(REPO)/services/connector-whatsapp" && set -a && source "$(ENV_DIR)/connector.env" && set +a && exec uvicorn main:app --host 0.0.0.0 --port 8000' \
			> "$(LOG_DIR)/connector.log" 2>&1 & echo $$! > "$(PID_DIR)/connector.pid"; \
		sleep 1; \
		kill -0 $$(cat "$(PID_DIR)/connector.pid") 2>/dev/null \
			&& echo "  connector: iniciado  → http://localhost:8000" \
			|| { echo "  ERROR connector. Ver: $(LOG_DIR)/connector.log"; tail -n 20 "$(LOG_DIR)/connector.log"; rm -f "$(PID_DIR)/connector.pid"; exit 1; }; \
	fi

# start-orchestrator: HOMOLOGADO con PRD (S7) — mismo entrypoint que Render
# (render.yaml: uvicorn server:app, web service con el worker en thread de
# fondo y /health). Antes corría `python3.11 main.py` (sin /health → no
# homologado). Puerto local fijo 8002.
start-orchestrator: _check
	@if [ -f "$(PID_DIR)/orchestrator.pid" ] && kill -0 $$(cat "$(PID_DIR)/orchestrator.pid") 2>/dev/null; then \
		echo "  orchestrator: ya corriendo"; \
	else \
		rm -f "$(PID_DIR)/orchestrator.pid"; \
		python3.11 "$(REPO)/scripts/dev_env_for_service.py" orchestrator --out "$(ENV_DIR)/orchestrator.env" || exit 1; \
		nohup $(CLEAN_ENV) bash -c 'cd "$(REPO)/services/ai-orchestrator" && set -a && source "$(ENV_DIR)/orchestrator.env" && set +a && exec uvicorn server:app --host 0.0.0.0 --port 8002' \
			> "$(LOG_DIR)/orchestrator.log" 2>&1 & echo $$! > "$(PID_DIR)/orchestrator.pid"; \
		sleep 1; \
		kill -0 $$(cat "$(PID_DIR)/orchestrator.pid") 2>/dev/null \
			&& echo "  orchestrator: iniciado → http://localhost:8002 (server:app, homologado PRD)" \
			|| { echo "  ERROR orchestrator. Ver: $(LOG_DIR)/orchestrator.log"; tail -n 20 "$(LOG_DIR)/orchestrator.log"; rm -f "$(PID_DIR)/orchestrator.pid"; exit 1; }; \
	fi

# ── Stop servicios ────────────────────────────────────────────────────────────

define _stop
	@pidfile="$(PID_DIR)/$(1).pid"; \
	if [ -f "$$pidfile" ]; then \
		pid=$$(cat "$$pidfile"); \
		kill "$$pid" 2>/dev/null || true; \
		sleep 1; \
		kill -0 "$$pid" 2>/dev/null && kill -9 "$$pid" 2>/dev/null || true; \
		rm -f "$$pidfile"; \
		echo "  $(1): detenido"; \
	fi
endef

stop-web:         ; $(call _stop,web)
stop-api:         ; $(call _stop,api)
stop-connector:   ; $(call _stop,connector)
stop-orchestrator:; $(call _stop,orchestrator)

# ── Túneles ngrok (internos) ──────────────────────────────────────────────────

_tunnel-api:
	@if [ -z "$(NGROK_AUTHTOKEN)" ]; then \
		echo "  [ngrok-api] NGROK_AUTHTOKEN no configurado en .env — túnel omitido"; \
	elif [ -f "$(PID_DIR)/ngrok-api.pid" ] && kill -0 $$(cat "$(PID_DIR)/ngrok-api.pid") 2>/dev/null; then \
		echo "  ngrok-api: ya corriendo"; \
	else \
		rm -f "$(PID_DIR)/ngrok-api.pid"; \
		domain_flag=""; [ -n "$(NGROK_DOMAIN_API)" ] && domain_flag="--domain=$(NGROK_DOMAIN_API)"; \
		nohup bash -c "exec ngrok http 8001 --authtoken='$(NGROK_AUTHTOKEN)' $$domain_flag --log=stdout --log-format=logfmt" \
			> "$(LOG_DIR)/ngrok-api.log" 2>&1 & echo $$! > "$(PID_DIR)/ngrok-api.pid"; \
		sleep 3; \
		kill -0 $$(cat "$(PID_DIR)/ngrok-api.pid") 2>/dev/null \
			&& echo "  ngrok-api: iniciado  → https://$(NGROK_DOMAIN_API)" \
			|| { echo "  ERROR ngrok-api. Ver: $(LOG_DIR)/ngrok-api.log"; tail -n 10 "$(LOG_DIR)/ngrok-api.log"; rm -f "$(PID_DIR)/ngrok-api.pid"; }; \
	fi

_tunnel-connector:
	@if [ -z "$(NGROK_AUTHTOKEN_CONNECTOR)" ]; then \
		echo "  [ngrok-connector] NGROK_AUTHTOKEN_CONNECTOR no configurado en .env — túnel omitido"; \
	elif [ -f "$(PID_DIR)/ngrok-connector.pid" ] && kill -0 $$(cat "$(PID_DIR)/ngrok-connector.pid") 2>/dev/null; then \
		echo "  ngrok-connector: ya corriendo"; \
	else \
		rm -f "$(PID_DIR)/ngrok-connector.pid"; \
		domain_flag=""; [ -n "$(NGROK_DOMAIN_CONNECTOR)" ] && domain_flag="--domain=$(NGROK_DOMAIN_CONNECTOR)"; \
		nohup bash -c "exec ngrok http 8000 --authtoken='$(NGROK_AUTHTOKEN_CONNECTOR)' $$domain_flag --log=stdout --log-format=logfmt" \
			> "$(LOG_DIR)/ngrok-connector.log" 2>&1 & echo $$! > "$(PID_DIR)/ngrok-connector.pid"; \
		sleep 3; \
		kill -0 $$(cat "$(PID_DIR)/ngrok-connector.pid") 2>/dev/null \
			&& echo "  ngrok-connector: iniciado  → https://$(NGROK_DOMAIN_CONNECTOR)" \
			|| { echo "  ERROR ngrok-connector. Ver: $(LOG_DIR)/ngrok-connector.log"; tail -n 10 "$(LOG_DIR)/ngrok-connector.log"; rm -f "$(PID_DIR)/ngrok-connector.pid"; }; \
	fi

_tunnel-down:
	@for svc in ngrok-api ngrok-connector; do \
		pidfile="$(PID_DIR)/$$svc.pid"; \
		if [ -f "$$pidfile" ]; then \
			pid=$$(cat "$$pidfile"); \
			kill "$$pid" 2>/dev/null || true; \
			sleep 1; \
			kill -0 "$$pid" 2>/dev/null && kill -9 "$$pid" 2>/dev/null || true; \
			rm -f "$$pidfile"; \
			echo "  $$svc: detenido"; \
		fi; \
	done

# ── Limpieza ──────────────────────────────────────────────────────────────────

clean:
	@rm -rf "$(LOG_DIR)" "$(PID_DIR)"
	@echo "Logs y PIDs eliminados."
