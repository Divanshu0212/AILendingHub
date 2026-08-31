# Phase 0 developer entrypoints. Everything here runs with stdlib Python 3.11+
# plus PyYAML. No Docker, no cluster, no bank connection required.
PY ?= python3
export PYTHONPATH := src

.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: check
check: grounding registry test  ## Run every gate that CI runs

.PHONY: grounding
grounding:  ## Enforce Master §2 grounding rules (TBD placeholders, definitions imports)
	$(PY) tools/check_grounding.py

.PHONY: registry
registry:  ## Validate the source registry against its schema (WS-0.1.1)
	$(PY) tools/validate_source_registry.py

.PHONY: schemas
schemas:  ## Check stream schema backward-compatibility (WS-0.1.4)
	$(PY) tools/check_schema_compatibility.py

.PHONY: test
test:  ## Run the test suite (stdlib unittest; pytest also works)
	$(PY) -m unittest discover -s tests -t . -v

.PHONY: audit-joins
audit-joins:  ## Identity-spine join-rate audit report (WS-0.1.3, gate >= 99.5%)
	$(PY) -m lending_hub.identity.audit --out reports/join_rate_audit.json

.PHONY: reconcile
reconcile:  ## GL reconciliation report (WS-0.1.5, gate <= 0.1% delta)
	$(PY) -m lending_hub.lakehouse.reconcile --out reports/gl_reconciliation.json

.PHONY: repro
repro:  ## Reproducibility test: same triplet twice -> identical metrics (WS-0.2.3)
	$(PY) -m lending_hub.mlops.reproducibility_test

.PHONY: loadtest
loadtest:  ## Serving-path load test (WS-0.2.4, p99 feature < 100ms / score < 500ms)
	$(PY) -m lending_hub.serving.loadtest --out reports/loadtest.json

.PHONY: parity
parity:  ## WS-0.4 parity harness (batch path vs serving path)
	$(PY) -m lending_hub.serving.parity --out reports/parity.json

.PHONY: trackp-p1
trackp-p1:  ## Run WS-1.1 end to end on Track P data (needs datasets/, see DATA_SOURCING)
	$(PY) -m lending_hub.scoring.experiment --out reports/trackP_p1_home_credit.json

.PHONY: gate
gate: check schemas  ## Run every gate script and assemble the evidence pack
	-$(PY) -m lending_hub.identity.audit --out reports/join_rate_audit.json
	-$(PY) -m lending_hub.lakehouse.reconcile --out reports/gl_reconciliation.json
	-$(PY) -m lending_hub.mlops.reproducibility_test
	-$(PY) -m lending_hub.serving.loadtest --out reports/loadtest.json
	-$(PY) -m lending_hub.serving.parity --out reports/parity.json
	$(PY) tools/gate_report.py --out reports/phase0_gate.md
