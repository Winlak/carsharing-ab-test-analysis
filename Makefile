.PHONY: install data analyze notebook reproduce audit test lint check clean-generated

PYTHON ?= python3
DATA_DIR ?= data/generated
N_USERS ?= 60000

install:
	$(PYTHON) -m pip install -r requirements.txt

data:
	$(PYTHON) -m src.generate_data --output-dir $(DATA_DIR) --n-users $(N_USERS) --seed 20250812

analyze:
	$(PYTHON) -m src.run_analysis --data-dir $(DATA_DIR) --sql-file sql/experiment_mart.sql --output-dir reports

notebook:
	$(PYTHON) -m jupyter nbconvert --execute --to notebook --inplace notebooks/ab_test_analysis.ipynb --ExecutePreprocessor.timeout=180

reproduce: data analyze notebook

reproduce-ci:
	$(PYTHON) -m src.generate_data --output-dir $(DATA_DIR) --n-users 60000 --seed 20250812
	$(PYTHON) -m src.run_analysis --data-dir $(DATA_DIR) --sql-file sql/experiment_mart.sql --output-dir reports
	$(PYTHON) -m jupyter nbconvert --execute --to notebook --inplace notebooks/ab_test_analysis.ipynb --ExecutePreprocessor.timeout=180

audit:
	$(PYTHON) -m scripts.validate_delivery

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests scripts

check: lint test reproduce-ci audit

clean-generated:
	rm -rf data/generated
