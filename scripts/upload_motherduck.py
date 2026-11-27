"""Push the locally built DuckDB warehouse (raw + analytics schemas) to MotherDuck.

    MOTHERDUCK_TOKEN=... python scripts/upload_motherduck.py [--database pockettoons]

Run `make build` first (or use `make upload-motherduck`, which does both). The
token is read from the environment or from .env and is never printed. Use a
read/write token here; give the API a read-only (read scaling) token.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv_lite import load_env  # noqa: E402

TABLES = {
    "raw": ["users", "sessions", "content_views", "transactions", "content_catalog", "marketing_spend"],
    "analytics": ["users", "sessions", "content_views", "transactions", "content_catalog",
                  "marketing_spend", "fct_user_day", "fct_user_month", "fct_transactions"],
}


def main(argv=None) -> int:
    load_env(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--database", default=os.environ.get("PT_MD_DATABASE") or "pockettoons")
    ap.add_argument("--local", default=str(ROOT / "data" / "pockettoons.duckdb"))
    args = ap.parse_args(argv)

    if not os.environ.get("MOTHERDUCK_TOKEN"):
        sys.exit("MOTHERDUCK_TOKEN is not set (environment or .env).")
    local = Path(args.local)
    if not local.exists():
        sys.exit(f"{local} not found: run `make build` first.")
    if not args.database.replace("_", "").isalnum():
        sys.exit("Database name must be letters, digits and underscores.")

    # Local counts first, so we can verify the upload.
    with duckdb.connect(str(local), read_only=True) as con:
        expected = {f"{s}.{t}": con.execute(f"SELECT count(*) FROM {s}.{t}").fetchone()[0]
                    for s, ts in TABLES.items() for t in ts}

    md = duckdb.connect("md:")                      # token comes from MOTHERDUCK_TOKEN
    md.execute(f"ATTACH '{local.as_posix()}' AS pt_local (READ_ONLY)")
    print(f"uploading {local.name} -> md:{args.database} ...")
    md.execute(f"CREATE OR REPLACE DATABASE {args.database} FROM pt_local")
    md.execute("DETACH pt_local")

    bad = []
    for name, n in expected.items():
        got = md.execute(f"SELECT count(*) FROM {args.database}.{name}").fetchone()[0]
        print(f"  {name:28s} {got:>11,} rows" + ("" if got == n else f"  (expected {n:,})"))
        if got != n:
            bad.append(name)
    md.close()
    if bad:
        sys.exit(f"row counts differ for: {', '.join(bad)}")
    print(f"done: set PT_MD_DATABASE={args.database} (and a read-only MOTHERDUCK_TOKEN) on the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
