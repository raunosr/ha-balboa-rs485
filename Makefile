PYTHON ?= python

.PHONY: test lint simulator smoke lab

test:
	$(PYTHON) -m tools.dev test

lint:
	$(PYTHON) -m tools.dev lint

simulator:
	$(PYTHON) -m tools.dev simulator

smoke:
	$(PYTHON) -m tools.dev smoke

lab:
	$(PYTHON) -m tools.dev lab
