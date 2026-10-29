.PHONY: up down test lint format demo demo-all rehearsal latency-measure activation-measure stack-up stack-down

up:
	docker compose up

down:
	docker compose down

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run mypy services shared

format:
	uv run black .
	uv run ruff check --fix .

# --- demo scenarios ---------------------------------------------------------
#
# `make demo SCENARIO=<name>` brings the live stack up pointed at the
# scenario's sensing YAML, runs the matching Python orchestrator under
# demos/scenarios/, and emits a markdown report to
# demos/scenarios/reports/<name>.md.
#
# `wifi_vs_5g` reuses `fire_ignition.yaml` as the underlying sensing source
# (the comparison is on the dispatcher's simulated network mode, not on the
# input workload).

SCENARIO ?= fire_ignition

# Map scenario name → sensing YAML.
_yaml_for = $(if $(filter wifi_vs_5g,$(1)),fire_ignition,$(1))

demo:
	@yaml=$(call _yaml_for,$(SCENARIO)); \
	if [ ! -f "demos/mock_data/scenarios/$$yaml.yaml" ]; then \
	    echo "no such sensing YAML: demos/mock_data/scenarios/$$yaml.yaml"; exit 2; fi; \
	if [ ! -f "demos/scenarios/$(SCENARIO).py" ]; then \
	    echo "no such scenario script: demos/scenarios/$(SCENARIO).py"; exit 2; fi; \
	echo "--- bringing up stack with SCENARIO=$$yaml ---"; \
	SCENARIO=$$yaml docker compose up -d redis mosquitto slice_control_mock actuators_mock; \
	SCENARIO=$$yaml docker compose up -d --force-recreate \
	    sensing vision fusion vlm agent action console_api; \
	echo "--- waiting 8 s for services to settle ---"; \
	sleep 8; \
	uv run python -m demos.scenarios.$(SCENARIO); rc=$$?; \
	docker compose stop \
	    console_api action agent vlm fusion vision sensing \
	    actuators_mock slice_control_mock mosquitto redis \
	    >/dev/null 2>&1 || true; \
	exit $$rc

demo-all:
	@for scen in medical_emergency fire_ignition wifi_vs_5g; do \
	    echo ""; echo "============================"; \
	    echo " scenario: $$scen"; \
	    echo "============================"; \
	    $(MAKE) --no-print-directory demo SCENARIO=$$scen || exit $$?; \
	done
	@echo ""; echo "All three reports under demos/scenarios/reports/:"
	@ls -1 demos/scenarios/reports/ | grep -v gitkeep || true

# --- dress rehearsal --------------------------------------------------------
#
# `make rehearsal` runs all three scenarios back-to-back with a 30 s
# settle gap between runs (per Prompt 10) and emits a combined
# REHEARSAL.md summary alongside the per-scenario reports.
REHEARSAL_GAP_SECONDS ?= 30

rehearsal:
	@start=$$(date +%s); \
	for scen in medical_emergency fire_ignition wifi_vs_5g; do \
	    echo ""; echo "==============================="; \
	    echo "  rehearsal: $$scen"; \
	    echo "==============================="; \
	    $(MAKE) --no-print-directory demo SCENARIO=$$scen || exit $$?; \
	    if [ "$$scen" != "wifi_vs_5g" ]; then \
	        echo "--- 30 s settle gap before next scenario ---"; \
	        sleep $(REHEARSAL_GAP_SECONDS); \
	    fi; \
	done; \
	uv run python -m demos.scenarios.rehearsal_summary --since $$start; \
	end=$$(date +%s); \
	echo ""; echo "Rehearsal finished in $$((end - start))s"

# --- activation measurement -------------------------------------------------
#
# `make activation-measure` runs mock_idle (steady state) + fire_ignition
# (one incident) against the live stack and reports the Layer C/D
# activation reduction vs running C/D on every frame.
activation-measure:
	SCENARIO=fire_ignition docker compose up -d \
	    redis mosquitto sensing vision fusion vlm agent \
	    slice_control_mock actuators_mock action console_api
	@sleep 8
	uv run python -m demos.latency_harness.activation

# --- latency harness --------------------------------------------------------
#
# `make latency-measure` brings up the live stack with fusion's emission
# cooldown overridden to 0.05 s, drives 100 synthetic triggers per
# network mode, and produces a CSV + matplotlib PNG + markdown report
# under demos/latency_harness/results/.
HARNESS_COUNT ?= 100

latency-measure:
	SCENARIO=fire_ignition docker compose up -d redis mosquitto slice_control_mock actuators_mock
	AXON_COOLDOWN_OVERRIDE_SECONDS=0.05 SCENARIO=fire_ignition \
	    docker compose up -d --force-recreate \
	    sensing vision fusion vlm agent action console_api
	@echo "--- waiting 8 s for services to settle ---"
	@sleep 8
	uv run python -m demos.latency_harness.harness --count $(HARNESS_COUNT); rc=$$?; \
	docker compose stop \
	    console_api action agent vlm fusion vision sensing \
	    actuators_mock slice_control_mock mosquitto redis \
	    >/dev/null 2>&1 || true; \
	exit $$rc
