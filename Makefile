PY ?= python
.PHONY: setup data dbt build truth upload-motherduck test ask gm eval api web report docker

setup:            ## install Python deps
	$(PY) -m pip install -r requirements-dev.txt
data:             ## generate synthetic data (DuckDB + SQLite)
	$(PY) data/generate_data.py --sqlite
dbt:              ## build staging + marts, run data tests
	cd dbt && DBT_PROFILES_DIR=. dbt build
build: data dbt truth
upload-motherduck: build  ## regenerate + dbt, then push the DuckDB file to MotherDuck (needs MOTHERDUCK_TOKEN)
	$(PY) scripts/upload_motherduck.py
truth:            ## recompute the eval answer key from the DB
	$(PY) -m eval.ground_truth
test:
	$(PY) -m pytest
ask:              ## make ask Q="What was MAU in October 2026?"
	$(PY) cli.py "$(Q)"
gm:               ## run the GM investigation, saves outputs/investigation_raw.md
	$(PY) cli.py --gm
eval:
	$(PY) -m eval.run_eval
api:
	uvicorn api.main:app --reload --port 8000
web:
	cd web && npm install && npm run dev
report:
	$(PY) report/build_report.py
docker:
	docker build -t pockettoons-agent . && docker run --rm -p 8000:8000 --env-file .env pockettoons-agent
