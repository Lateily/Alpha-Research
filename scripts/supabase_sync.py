#!/usr/bin/env python3
"""
AR Platform — Supabase Sync
Reads vp_snapshot.json + OHLCV data from public/data/ and upserts into Supabase.

Setup:
  1. Create a Supabase project at supabase.com (free tier)
  2. Run the SQL schema below in Supabase SQL editor
  3. Add to GitHub Secrets:
       SUPABASE_URL   = https://xxxx.supabase.co
       SUPABASE_KEY   = your-service-role-key (Settings → API → service_role)
  4. This script is called by GitHub Actions after fetch_data.py

SQL Schema (run once in Supabase SQL editor):
──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vp_scores (
  ticker             VARCHAR(12)   NOT NULL,
  date               DATE          NOT NULL,
  vp_score           NUMERIC(4,1),
  expectation_gap    NUMERIC(4,1),
  fundamental_accel  NUMERIC(4,1),
  narrative_shift    NUMERIC(4,1),
  low_coverage       NUMERIC(4,1),
  catalyst_proximity NUMERIC(4,1),
  close              NUMERIC(14,4),
  volume             BIGINT,
  updated_at         TIMESTAMPTZ   DEFAULT NOW(),
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS ohlcv (
  ticker  VARCHAR(12)   NOT NULL,
  date    DATE          NOT NULL,
  open    NUMERIC(14,4),
  high    NUMERIC(14,4),
  low     NUMERIC(14,4),
  close   NUMERIC(14,4),
  volume  BIGINT,
  market  VARCHAR(4),
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS consensus_snapshots (
  ticker          VARCHAR(12) NOT NULL,
  date            DATE        NOT NULL,
  source          VARCHAR(20),
  target_median   NUMERIC(14,4),
  target_high     NUMERIC(14,4),
  target_low      NUMERIC(14,4),
  num_analysts    INTEGER,
  fy1_eps_median  NUMERIC(10,4),
  fy1_profit_median NUMERIC(20,2),
  raw_json        JSONB,
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS research_notes (
  id         SERIAL PRIMARY KEY,
  ticker     VARCHAR(12),
  date       DATE,
  note_type  VARCHAR(30),
  content    TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for time-series queries
CREATE INDEX IF NOT EXISTS idx_vp_ticker_date ON vp_scores (ticker, date DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date ON ohlcv (ticker, date DESC);
──────────────────────────────────────────────────────────────────────────────
"""

import json, os, sys, time
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

def get_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set.")
        print("       Add them as GitHub Secrets or set locally before running.")
        sys.exit(1)
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        print("ERROR: supabase not installed. Run: pip install supabase")
        sys.exit(1)


def upsert_with_retry(client, table, data, retries=3):
    """Upsert with exponential backoff."""
    for attempt in range(retries):
        try:
            client.table(table).upsert(data).execute()
            return True
        except Exception as e:
            wait = 2 ** attempt
            print(f"  Retry {attempt+1}/{retries} for {table}: {e} (wait {wait}s)")
            time.sleep(wait)
    print(f"  FAILED: {table} after {retries} retries")
    return False


def sync_vp_scores(client):
    """Upsert today's VP scores."""
    snap_file = DATA_DIR / "vp_snapshot.json"
    if not snap_file.exists():
        print("  vp_snapshot.json not found — skipping VP sync"); return 0

    with open(snap_file) as f:
        snap = json.load(f)

    rows = snap.get("snapshots", [])
    if not rows:
        print("  No VP snapshots to sync"); return 0

    # Supabase upsert (handles duplicate ticker+date gracefully)
    success = upsert_with_retry(client, "vp_scores", rows)
    count = len(rows) if success else 0
    print(f"  VP scores: {count} rows upserted for {snap.get('date')}")
    return count


def sync_ohlcv(client):
    """Upsert OHLCV data for all focus stocks."""
    ohlc_files = list(DATA_DIR.glob("ohlc_*.json"))
    total = 0
    for fpath in ohlc_files:
        try:
            with open(fpath) as f:
                data = json.load(f)
            ticker = data.get("ticker", fpath.stem.replace("ohlc_", "").replace("_", "."))
            market = "HK" if ticker.endswith(".HK") else ("SH" if "SH" in ticker else "SZ")
            rows = []
            for candle in data.get("data", []):
                rows.append({
                    "ticker": ticker,
                    "date":   candle["date"],
                    "open":   candle.get("open"),
                    "high":   candle.get("high"),
                    "low":    candle.get("low"),
                    "close":  candle.get("close"),
                    "volume": candle.get("volume"),
                    "market": market,
                })
            if rows:
                # Batch in chunks of 500 to stay within Supabase request limits
                for i in range(0, len(rows), 500):
                    upsert_with_retry(client, "ohlcv", rows[i:i+500])
                total += len(rows)
                print(f"  OHLCV {ticker}: {len(rows)} candles")
        except Exception as e:
            print(f"  OHLCV {fpath.name} error: {e}")
    print(f"  OHLCV total: {total} rows")
    return total


def sync_consensus(client):
    """Upsert consensus estimates."""
    mdf = DATA_DIR / "market_data.json"
    if not mdf.exists(): return 0

    with open(mdf) as f:
        mdata = json.load(f)

    consensus = mdata.get("consensus", {})
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for ticker, cons in consensus.items():
        rows.append({
            "ticker":            ticker,
            "date":              today,
            "source":            cons.get("source"),
            "target_median":     cons.get("target_median"),
            "target_high":       cons.get("target_high"),
            "target_low":        cons.get("target_low"),
            "num_analysts":      cons.get("num_analysts"),
            "fy1_eps_median":    cons.get("fy1_eps_median"),
            "fy1_profit_median": cons.get("fy1_profit_median"),
            "raw_json":          json.dumps(cons),
        })
    if rows:
        upsert_with_retry(client, "consensus_snapshots", rows)
    print(f"  Consensus: {len(rows)} rows")
    return len(rows)


def main():
    print(f"{'='*50}")
    print(f"AR Platform — Supabase Sync")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    client = get_client()

    print("[1/3] Syncing VP Scores...")
    vp_count = sync_vp_scores(client)

    print("\n[2/3] Syncing OHLCV History...")
    ohlcv_count = sync_ohlcv(client)

    print("\n[3/3] Syncing Consensus Estimates...")
    cons_count = sync_consensus(client)

    print(f"\n{'='*50}")
    print(f"DONE: {vp_count} VP rows | {ohlcv_count} OHLCV rows | {cons_count} consensus rows")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
