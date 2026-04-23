import sqlite3
import pandas as pd
import numpy as np
from database import get_connection, DB_PATH


def _compute_metrics(group: pd.DataFrame) -> dict:
    non_cancelled = group[group["is_cancelled"] == 0]["delay_seconds"].dropna()
    n_total = len(group)
    n_obs = len(non_cancelled)

    if n_obs == 0:
        return {
            "n_observations": n_total,
            "mean_delay": None,
            "median_delay": None,
            "p85_delay": None,
            "p95_delay": None,
            "std_delay": None,
            "on_time_rate": None,
            "cancellation_rate": len(group[group["is_cancelled"] == 1])
            / max(n_total, 1),
            "excess_wait_time": None,
        }

    return {
        "n_observations": n_total,
        "mean_delay": round(float(non_cancelled.mean()), 2),
        "median_delay": round(float(non_cancelled.median()), 2),
        "p85_delay": round(float(np.percentile(non_cancelled, 85)), 2),
        "p95_delay": round(float(np.percentile(non_cancelled, 95)), 2),
        "std_delay": round(float(non_cancelled.std()), 2),
        "on_time_rate": round(float((non_cancelled.abs() <= 60).mean()), 4),
        "cancellation_rate": round(float(group["is_cancelled"].mean()), 4),
        "excess_wait_time": round(float(non_cancelled.clip(lower=0).mean() / 60), 4),
    }


def compute_all_metrics(
    conn: sqlite3.Connection, window_start: str = None, window_end: str = None
) -> pd.DataFrame:
    """
    Compute metrics at stop, route, and region level.
    Returns a DataFrame ready to insert into reliability_metrics.
    """
    # Use cleaned view if available, otherwise raw table
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    ]
    source = (
        "delay_observations_clean"
        if "delay_observations_clean" in tables
        else "delay_observations"
    )

    query = f"SELECT * FROM {source}"
    filters = []
    if window_start:
        filters.append(f"collected_at >= '{window_start}'")
    if window_end:
        filters.append(f"collected_at <= '{window_end}'")
    if filters:
        query += " WHERE " + " AND ".join(filters)

    obs = pd.read_sql(query, conn)

    if "region" not in obs.columns:
        if "stop_regions" in tables:
            reg = pd.read_sql("SELECT stop_id, region FROM stop_regions", conn)
        else:
            reg = pd.read_sql("SELECT stop_id, zone_id AS region FROM stops", conn)
        obs = obs.merge(reg, on="stop_id", how="left")

    all_rows = []

    for route_id, grp in obs.groupby("route_id"):
        m = _compute_metrics(grp)
        all_rows.append(
            {
                "aggregation_level": "route",
                "entity_id": route_id,
                "window_start": window_start,
                "window_end": window_end,
                **m,
            }
        )

    for stop_id, grp in obs.groupby("stop_id"):
        m = _compute_metrics(grp)
        all_rows.append(
            {
                "aggregation_level": "stop",
                "entity_id": stop_id,
                "window_start": window_start,
                "window_end": window_end,
                **m,
            }
        )

    for region, grp in obs.groupby("region"):
        m = _compute_metrics(grp)
        all_rows.append(
            {
                "aggregation_level": "region",
                "entity_id": region,
                "window_start": window_start,
                "window_end": window_end,
                **m,
            }
        )

    return pd.DataFrame(all_rows)


def save_metrics(conn: sqlite3.Connection, metrics_df: pd.DataFrame) -> None:
    metrics_df.to_sql("reliability_metrics", conn, if_exists="replace", index=False)
    conn.commit()
    print(f"[metrics] Saved {len(metrics_df)} metric rows to DB.")


if __name__ == "__main__":
    with get_connection() as conn:
        df = compute_all_metrics(conn)
        save_metrics(conn, df)
        print(df.groupby("aggregation_level")["entity_id"].count())
        region_df = df[df["aggregation_level"] == "region"].set_index("entity_id")
        print("\nRegion reliability summary:")
        print(region_df[["mean_delay", "cancellation_rate", "on_time_rate"]].round(3))
