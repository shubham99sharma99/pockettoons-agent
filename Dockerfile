# ---- build stage: generate the data and build the dbt models into one DuckDB file
FROM python:3.13-slim AS build
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY data/config.py data/generate_data.py data/
COPY dbt/ dbt/
RUN python data/generate_data.py \
 && cd dbt && DBT_PROFILES_DIR=. dbt build --quiet \
 && rm -rf target logs

# ---- runtime stage: API only, DuckDB file baked in, opened read-only
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -m app
COPY agent/ agent/
COPY api/ api/
COPY eval/ eval/
COPY dbt/models/ dbt/models/
COPY dotenv_lite.py cli.py ./
COPY --from=build /app/data/pockettoons.duckdb data/pockettoons.duckdb
RUN chown -R app /app/eval
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
