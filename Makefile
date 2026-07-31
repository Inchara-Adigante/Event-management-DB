# Shortcuts. Override the connection with DATABASE_URL, e.g.
#   make setup DATABASE_URL=postgresql://postgres:postgres@localhost:5432/event_mgmt
PY ?= .venv/bin/python

.PHONY: venv db setup seed test queries bench docs all

venv:
	python3 -m venv .venv && $(PY) -m pip install -r requirements.txt

db:
	docker compose up -d --wait

setup:              ## create the database from scratch and apply all migrations
	$(PY) scripts/migrate.py --reset

seed:               ## load ~2 million rows of realistic data (about 90 s)
	$(PY) db/seed/generate.py --as-of 2026-07-28

test:
	$(PY) -m pytest

queries:            ## run the 18 analytics questions, write docs/analytics_results.md
	$(PY) scripts/run_queries.py

bench:              ## index and lock-contention experiments, write docs/performance_results.json
	$(PY) scripts/benchmark.py

docs:
	$(PY) scripts/data_dictionary.py

all: setup seed test queries docs
