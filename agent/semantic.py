"""Load the data dictionary and metric catalog the agent is allowed to see.

Sources (single source of truth, no copies):
  * dbt/models/staging/schema.yml and dbt/models/marts/schema.yml: table and
    column descriptions (the data dictionary);
  * dbt/models/semantic/metrics.yml: governed MetricFlow metrics;
  * agent/semantic_layer.yaml: segments, periods, product facts and analytical
    definitions.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DBT_MODELS = ROOT / "dbt" / "models"
AGENT_LAYER = Path(__file__).resolve().parent / "semantic_layer.yaml"
PLAYBOOK = Path(__file__).resolve().parent / "prompts" / "playbook.md"


@lru_cache(maxsize=1)
def data_dictionary() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in [DBT_MODELS / "staging" / "schema.yml", DBT_MODELS / "marts" / "schema.yml"]:
        doc = yaml.safe_load(f.read_text())
        for m in doc.get("models", []):
            if m["name"] == "metricflow_time_spine":
                continue
            out[m["name"]] = {
                "description": m.get("description", ""),
                "columns": {c["name"]: c.get("description", "") for c in m.get("columns", [])},
            }
    return out


@lru_cache(maxsize=1)
def dbt_metrics() -> list[dict]:
    doc = yaml.safe_load((DBT_MODELS / "semantic" / "metrics.yml").read_text())
    out = []
    for m in doc["metrics"]:
        meta = m.get("meta", {}) or {}
        entry = {"name": m["name"], "label": m.get("label"), "description": m.get("description"),
                 "type": m["type"], "source": "dbt_semantic_layer"}
        if m["type"] == "ratio":
            entry["ratio_of"] = [m["type_params"]["numerator"], m["type_params"]["denominator"]]
        for k in ("grain", "sql", "caveat", "quarterly"):
            if k in meta:
                entry[k] = meta[k]
        out.append(entry)
    return out


@lru_cache(maxsize=1)
def agent_layer() -> dict:
    return yaml.safe_load(AGENT_LAYER.read_text())


def metric_catalog() -> dict:
    layer = agent_layer()
    return {
        "dialect": layer.get("dialect"),
        "notes": layer.get("notes", []),
        "product_facts": layer.get("product_facts", []),
        "segments": layer.get("segments", {}),
        "periods": layer.get("periods", {}),
        "metrics": dbt_metrics(),
        "analytical_definitions": layer.get("definitions", {}),
    }


def playbook() -> str:
    return PLAYBOOK.read_text()
