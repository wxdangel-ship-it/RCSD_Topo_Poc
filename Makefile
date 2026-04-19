.PHONY: ensure-env env-sync doctor test smoke

UV ?= uv
PYTHON ?= .venv/bin/python
UV_SYNC_ARGS ?= --python 3.10 --extra dev

ensure-env:
	@test -x "$(PYTHON)" || (echo "[BLOCK] Missing $(PYTHON). Run 'make env-sync' first."; exit 2)

env-sync:
	$(UV) sync $(UV_SYNC_ARGS)

doctor: ensure-env
	$(PYTHON) -m rcsd_topo_poc doctor

test: ensure-env
	$(PYTHON) -m pytest -q -s

smoke: ensure-env
	$(PYTHON) -m pytest -q -s -m smoke
