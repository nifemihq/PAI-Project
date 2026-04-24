"""
pipeline/temporal_stability.py
────────────────────────────────
Computes per-window route reliability metrics and stability scores
for temporal stability analysis across collection sessions.
"""
import sqlite3
import numpy as np
import pandas as pd

# ── Window definitions (UTC) ─────────────────────────────────────────────────
# Derived from actual collection session gaps > 5 minutes
WINDOWS = {
    "Thu Overnight/Morning": ("2026-04-23T01:00:00", "2026-04-23T09:03:00"),
    "Thu Afternoon/Evening": ("2026-04-23T14:49:00", "2026-04-23T18:45:00"),
    "Thu Late Evening":      ("2026-04-23T20:54:00", "2026-04-24T00:05:00"),
    "Fri Morning Rush":      ("2026-04-24T08:09:00", None),  # up to latest available
}

SHORT_NAMES = {
    "Thu Overnight/Morning": "Thu AM",
    "Thu Afternoon/Evening": "Thu PM",
    "Thu Late Evening":      "Thu Late",
    "Fri Morning Rush":      "Fri Rush",
}

WINDOW_ORDER = ["Thu AM", "Thu PM", "Thu Late", "Fri Rush"]

MIN_OBS_PER_WINDOW = 30


def compute_window_metrics(
    conn: sqlite3.Connection,
    window_start: str,
    window_end: str | None = None,
) -> pd.DataFrame:
    """Return route-level reliability metrics for one time window."""
    where = f"collected_at >= '{window_start}'"
    if window_end:
        where += f" AND collected_at < '{window_end}'"

    df = pd.read_sql(
        f"""
        SELECT o.route_id, o.delay_seconds, o.is_cancelled
        FROM   delay_observations o
        JOIN   routes r ON o.route_id = r.route_id
        WHERE  {where}
          AND  o.is_valid   = 1
          AND  o.is_outlier = 0
        """,
        conn,
    )
    if df.empty:
        return pd.DataFrame()

    rows = []
    for route_id, grp in df.groupby("route_id"):
        valid = grp[grp.is_cancelled == 0]["delay_seconds"].dropna()
        if len(valid) < MIN_OBS_PER_WINDOW:
            continue
        rows.append(
            {
                "route_id":          route_id,
                "n_obs":             int(len(grp)),
                "mean_delay":        float(valid.mean()),
                "median_delay":      float(valid.median()),
                "p85_delay":         float(np.percentile(valid, 85)),
                "std_delay":         float(valid.std()),
                "on_time_rate":      float((valid.abs() <= 60).mean()),
                "cancellation_rate": float(grp.is_cancelled.mean()),
                "excess_wait_time":  float(valid.clip(lower=0).mean() / 60),
            }
        )

    return pd.DataFrame(rows)


def build_temporal_profile(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Long-format DataFrame of route metrics across all windows.
    Columns: route_id, window, window_short, + metric columns.
    """
    dfs = []
    for name, (start, end) in WINDOWS.items():
        wdf = compute_window_metrics(conn, start, end)
        if wdf.empty:
            print(f"[temporal] {name}: no data")
            continue
        wdf["window"] = name
        wdf["window_short"] = SHORT_NAMES[name]
        print(f"[temporal] {name}: {len(wdf)} routes, {wdf.n_obs.sum():,} observations")
        dfs.append(wdf)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def compute_stability_scores(temporal_df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-route coefficient of variation of mean_delay across windows.
    Lower CV = more stable across time.
    """
    g = (
        temporal_df.groupby("route_id")["mean_delay"]
        .agg(n_windows="count", mean_across="mean", std_across="std")
        .reset_index()
    )
    g["cv"] = g["std_across"] / (g["mean_across"].abs() + 1e-9)
    return g.sort_values("cv", ascending=False).reset_index(drop=True)


def cluster_window_profiles(
    temporal_df: pd.DataFrame, cluster_map: pd.DataFrame
) -> pd.DataFrame:
    """
    Aggregate: mean of each metric per cluster per window.
    cluster_map must have [route_id, cluster] columns.
    """
    merged = temporal_df.merge(cluster_map[["route_id", "cluster"]], on="route_id", how="inner")
    merged = merged[merged.cluster != -1]
    agg = (
        merged.groupby(["cluster", "window_short"])
        .agg(
            mean_delay=("mean_delay", "mean"),
            on_time_rate=("on_time_rate", "mean"),
            cancellation_rate=("cancellation_rate", "mean"),
            n_routes=("route_id", "count"),
        )
        .reset_index()
    )
    order = [w for w in WINDOW_ORDER if w in agg["window_short"].values]
    agg["window_short"] = pd.Categorical(agg["window_short"], categories=order, ordered=True)
    return agg.sort_values(["cluster", "window_short"])
