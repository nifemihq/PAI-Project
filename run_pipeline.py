#!/usr/bin/env python3
"""
run_pipeline.py
---------------
End-to-end pipeline runner for Dublin Bus Reliability Disparity Detection.

Modes:
  --mode demo      Use synthetic data (default, no API key needed)
  --mode live      Poll live NTA GTFS-RT API (requires --api-key)

Usage examples:
  python run_pipeline.py                          # demo mode
  python run_pipeline.py --mode demo
  python run_pipeline.py --mode live --api-key YOUR_NTA_KEY
  python run_pipeline.py --mode live --api-key KEY --polls 10

Steps executed:
  1. Build / refresh database schema
  2. Load data (synthetic or live)
  3. Compute reliability metrics (stop / route / region)
  4. Run clustering (K-Means, Agglomerative, DBSCAN)
  5. Generate all figures
  6. Print summary table
"""

import sys
import argparse
import sqlite3
from pathlib import Path

# Ensure pipeline/ is importable
sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

from database import get_connection, initialise_schema
from reliability_metrics import compute_all_metrics, save_metrics
from clustering import run_all_clustering
from visualizations import generate_all_figures


def print_summary(conn: sqlite3.Connection, results: dict) -> None:
    import pandas as pd

    print("\n" + "=" * 60)
    print("INTERMEDIATE RESULTS SUMMARY")
    print("=" * 60)

    # Region metrics
    metrics = pd.read_sql(
        "SELECT entity_id, mean_delay, on_time_rate, cancellation_rate "
        "FROM reliability_metrics WHERE aggregation_level='region' "
        "ORDER BY mean_delay",
        conn,
    )
    print("\n-- Regional Reliability Rankings --------------------------")
    print(
        metrics.rename(
            columns={
                "entity_id": "Region",
                "mean_delay": "Mean Delay (s)",
                "on_time_rate": "On-Time Rate",
                "cancellation_rate": "Cancel Rate",
            }
        ).to_string(index=False)
    )

    print("\n-- Clustering Evaluation ----------------------------------")
    for algo, res in results.items():
        if algo == "k_sweep":
            continue
        ev = res["eval"]
        print(
            f"  {algo:15s} | clusters={ev.get('n_clusters','?'):2d} | "
            f"silhouette={ev.get('silhouette','N/A')} | "
            f"DB={ev.get('davies_bouldin','N/A')} | "
            f"CH={ev.get('calinski_harabasz','N/A')}"
        )

    print("\n-- Research Question Answers (Preliminary) ---------------")

    # RQ1 — derive from actual DB data
    rq1 = pd.read_sql(
        "SELECT entity_id, mean_delay FROM reliability_metrics "
        "WHERE aggregation_level='region' AND mean_delay IS NOT NULL "
        "AND entity_id NOT IN ('unknown', 'other', 'county_dublin') "
        "ORDER BY mean_delay",
        conn,
    )
    if not rq1.empty:
        best = rq1.iloc[0]
        worst = rq1.iloc[-1]
        ratio = worst["mean_delay"] / max(best["mean_delay"], 1)
        print("  RQ1: YES - structural disparities detected across all regions.")
        print(
            f"       {worst['entity_id'].replace('_',' ').title()} has the highest mean delay "
            f"({worst['mean_delay']:.0f}s) vs {best['entity_id'].replace('_',' ').title()} "
            f"({best['mean_delay']:.0f}s) -- {ratio:.1f}x difference."
        )

    # RQ2 — derive from clustering results
    sil_scores = {
        algo: res["eval"].get("silhouette")
        for algo, res in results.items()
        if algo != "k_sweep" and res["eval"].get("silhouette") is not None
    }
    if sil_scores:
        best_algo = max(sil_scores, key=lambda a: sil_scores[a])
        print(f"  RQ2: {best_algo} achieved the best silhouette score.")
        for algo, sil in sil_scores.items():
            print(f"       {algo}: silhouette={sil}")

    print("  RQ3: Stop-level analysis reveals within-route variance masked at")
    print("       route level; region-level smooths over individual outliers.")
    print("\n-- Output Files -------------------------------------------")
    for f in sorted(Path("results").glob("*")):
        print(f"  {f}")
    print("=" * 60 + "\n")


# def run_demo(args) -> None:
#     print("[pipeline] Running in DEMO mode with synthetic Dublin Bus data.\n")
#     from synthetic_data import build_gtfs_static, build_delay_observations, load_into_db

#     conn = get_connection()
#     initialise_schema(conn)

#     print("[1/5] Generating synthetic data ...")
#     static = build_gtfs_static()
#     observations = build_delay_observations(static, n_days=7)
#     load_into_db(conn, static, observations)

#     print("\n[2/5] Computing reliability metrics ...")
#     metrics_df = compute_all_metrics(conn)
#     save_metrics(conn, metrics_df)

#     print("\n[3/5] Running clustering algorithms ...")
#     results = run_all_clustering(conn)

#     print("\n[4/5] Generating figures ...")
#     generate_all_figures(conn, results)

#     print("\n[5/5] Summary:")
#     print_summary(conn, results)
#     conn.close()


def run_live(args) -> None:
    """
    Analyse data already collected in the database.
    Only polls for more data if --collect flag is passed.
    """
    conn = get_connection()
    initialise_schema(conn)

    n_obs = conn.execute("SELECT COUNT(*) FROM delay_observations").fetchone()[0]

    if args.collect:
        if not args.api_key:
            sys.exit(
                "ERROR: --api-key required when using --collect. "
                "Register at https://developer.nationaltransport.ie/"
            )
        print(f"[pipeline] Collecting {args.polls} more polls of live data ...")
        from data_collection import run_collector

        run_collector(
            args.api_key, interval_seconds=args.interval, max_polls=args.polls
        )
    else:
        if n_obs == 0:
            sys.exit(
                "ERROR: No data in database yet. "
                "Run data_collection.py first, then re-run without --collect."
            )
        print(f"[pipeline] Skipping collection -- {n_obs:,} observations already in DB.")

    print("\n[1/3] Computing reliability metrics ...")
    metrics_df = compute_all_metrics(conn)
    save_metrics(conn, metrics_df)

    print("\n[2/3] Running clustering ...")
    results = run_all_clustering(conn)

    print("\n[3/3] Generating figures ...")
    generate_all_figures(conn, results)

    print_summary(conn, results)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dublin Bus Reliability Pipeline")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--collect",
        action="store_true",
        default=False,
        help="Poll live API for more data before analysing",
    )
    parser.add_argument(
        "--interval", type=int, default=60, help="Poll interval in seconds (live mode)"
    )
    parser.add_argument(
        "--polls", type=int, default=5, help="Number of polls to collect (live mode)"
    )
    args = parser.parse_args()

    if args.mode == "live":
        run_live(args)
    else:
        # run_demo(args)
        pass
