.PHONY: test smoke

test:
	python -m pytest -q

smoke:
	python -m pytest -q -m smoke
