import sqlite3
import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
from pathlib import Path
from database import get_connection

RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PALETTE = {
    "city_centre": "#2196F3",
    "south_dublin": "#4CAF50",
    "north_dublin": "#FF9800",
    "west_dublin": "#F44336",
    "county_dublin": "#9C27B0",
    "other": "#795548",
}
CLUSTER_COLORS = ["#E63946", "#457B9D", "#2A9D8F", "#E9C46A", "#F4A261", "#264653"]

sns.set_theme(style="whitegrid", font_scale=1.15)


def _save(fig, name: str):
    path = RESULTS_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [viz] Saved {path.name}")
    return path


def fig_delay_distributions(conn: sqlite3.Connection):
    # Use clean view if available
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    ]
    source = (
        "delay_observations_clean"
        if "delay_observations_clean" in tables
        else "delay_observations o JOIN stops s ON o.stop_id=s.stop_id"
    )

    if "delay_observations_clean" in tables:
        obs = pd.read_sql(
            "SELECT delay_seconds, region FROM delay_observations_clean "
            "WHERE is_cancelled=0 AND delay_seconds IS NOT NULL "
            "AND (obs_id % 20 = 0)",
            conn,
        )
    else:
        obs = pd.read_sql(
            "SELECT o.delay_seconds, s.zone_id AS region "
            "FROM delay_observations o JOIN stops s ON o.stop_id=s.stop_id "
            "WHERE o.is_cancelled=0 AND o.delay_seconds IS NOT NULL",
            conn,
        )

    MAIN_REGIONS = ["city_centre", "south_dublin", "north_dublin", "west_dublin"]
    obs = obs[obs["region"].isin(MAIN_REGIONS)]

    obs = obs[obs["delay_seconds"].between(-120, 600)]

    fig, axes = plt.subplots(1, 4, figsize=(14, 4), sharey=True)
    region_labels = {
        "city_centre": "City Centre",
        "south_dublin": "South Dublin",
        "north_dublin": "North Dublin",
        "west_dublin": "West Dublin",
    }
    stats = []
    for ax, region in zip(axes, MAIN_REGIONS):
        grp = obs[obs["region"] == region]["delay_seconds"]
        if len(grp) < 10:
            continue
        grp.plot.kde(ax=ax, color=PALETTE[region], linewidth=2.2)
        ax.axvline(0, color="black", ls="--", lw=1.0, alpha=0.7)
        ax.axvline(60, color="grey", ls=":", lw=1.0, alpha=0.7)
        med = grp.median()
        ax.axvline(med, color=PALETTE[region], ls="-.", lw=1.2, alpha=0.8)
        on_time = (grp.abs() <= 60).mean() * 100
        ax.set_title(
            f"{region_labels[region]}\nMedian={med:.0f}s  OTR={on_time:.0f}%",
            fontsize=10,
        )
        ax.set_xlabel("Delay (seconds)")
        ax.set_xlim(-120, 600)
        stats.append((region, med, on_time))

    axes[0].set_ylabel("Density")
    fig.suptitle(
        "Delay Distributions by Region (Dublin Bus)\n"
        "Dashed = on time, dotted = +60s, dash-dot = median",
        fontsize=12,
    )
    plt.tight_layout()
    return _save(fig, "fig1_delay_distributions_by_region.png")


def fig_cancellation_rates(conn: sqlite3.Connection):
    metrics = pd.read_sql(
        "SELECT m.entity_id, m.cancellation_rate "
        "FROM reliability_metrics m "
        "WHERE m.aggregation_level='route'",
        conn,
    )

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    ]
    if "stop_regions" in tables:
        region_map = pd.read_sql(
            "SELECT DISTINCT t.route_id, sr.region "
            "FROM trips t "
            "JOIN stop_times st ON t.trip_id=st.trip_id "
            "JOIN stop_regions sr ON st.stop_id=sr.stop_id "
            "GROUP BY t.route_id",
            conn,
        )
        metrics = metrics.merge(
            region_map, left_on="entity_id", right_on="route_id", how="left"
        )
    else:
        metrics["region"] = "unknown"
    metrics = metrics[metrics["region"].isin(PALETTE.keys())]
    if metrics.empty:
        return _save(plt.figure(), "fig2_cancellation_rates_by_region.png")

    order = metrics.groupby("region")["cancellation_rate"].mean().sort_values().index

    fig, ax = plt.subplots(figsize=(9, 5))
    for i, region in enumerate(order):
        sub = metrics[metrics["region"] == region]["cancellation_rate"] * 100
        mean_val = sub.mean()
        err = min(sub.std(), mean_val) if len(sub) > 1 else 0
        ax.bar(
            i,
            mean_val,
            color=PALETTE[region],
            label=region.replace("_", " ").capitalize(),
            width=0.6,
            zorder=3,
        )
        ax.errorbar(
            i,
            mean_val,
            yerr=[[min(err, mean_val)], [err]],
            fmt="none",
            color="black",
            capsize=5,
            zorder=4,
        )
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([r.replace("_", " ").capitalize() for r in order])
    ax.set_ylabel("Mean Cancellation Rate (%)")
    ax.set_title("Route Cancellation Rates by Region\n(error bars = ±1 SD)")
    ax.legend()
    return _save(fig, "fig2_cancellation_rates_by_region.png")


def fig_route_heatmap(conn: sqlite3.Connection):
    routes_df = pd.read_sql("SELECT route_id, route_short_name FROM routes", conn)
    metrics = pd.read_sql(
        "SELECT m.entity_id, m.mean_delay, m.on_time_rate, "
        "       m.cancellation_rate, m.p85_delay, m.std_delay, m.n_observations "
        "FROM reliability_metrics m "
        "WHERE m.aggregation_level='route' AND m.n_observations >= 50",
        conn,
    )
    metrics = metrics.merge(
        routes_df, left_on="entity_id", right_on="route_id", how="left"
    )
    metrics["route_short_name"] = metrics["route_short_name"].fillna(
        metrics["entity_id"]
    )
    feat_cols = ["mean_delay", "p85_delay", "std_delay", "cancellation_rate"]

    metrics = metrics.nlargest(40, "n_observations")
    metrics["label"] = metrics["route_short_name"].where(
        metrics["route_short_name"].notna() & (metrics["route_short_name"] != ""),
        metrics["entity_id"].str[-8:],
    )
    pivot = metrics.set_index("label")[feat_cols]
    pivot_norm = (pivot - pivot.min()) / (pivot.max() - pivot.min() + 1e-9)
    pivot_norm = pivot_norm.sort_values("mean_delay", ascending=False)

    fig, ax = plt.subplots(figsize=(8, 11))
    sns.heatmap(
        pivot_norm,
        annot=pivot.loc[pivot_norm.index].round(0),
        fmt=".0f",
        cmap="RdYlGn_r",
        linewidths=0.4,
        cbar_kws={"label": "Normalised score (0=best, 1=worst)"},
        ax=ax,
    )
    ax.set_xlabel("Reliability Metric")
    ax.set_ylabel("Route")
    ax.set_title("Route-Level Reliability Heatmap\n(annotated with raw values)")
    ax.set_xticklabels(
        ["Mean Delay (s)", "P85 Delay (s)", "Std Dev (s)", "Cancel Rate"],
        rotation=30,
        ha="right",
    )
    return _save(fig, "fig3_route_reliability_heatmap.png")


def fig_clustering_scatter(results: dict):
    paths = []
    algo_meta = {
        "KMeans": ("fig4_kmeans_pca_scatter.png", "K-Means (k=4)"),
        "Agglomerative": (
            "fig5_agglomerative_pca_scatter.png",
            "Agglomerative (Ward, k=4)",
        ),
        "DBSCAN": ("fig6_dbscan_pca_scatter.png", "DBSCAN (ε=0.8)"),
    }
    for algo, (fname, title) in algo_meta.items():
        if algo not in results:
            continue
        df = results[algo]["data"]
        ev = results[algo]["eval"]
        n_c = ev.get("n_clusters", "?")

        fig, axes = plt.subplots(1, 2, figsize=(13, 5))

        for c in sorted(df["cluster"].unique()):
            sub = df[df["cluster"] == c]
            label = f"Cluster {c}" if c != -1 else "Noise"
            col = CLUSTER_COLORS[c % len(CLUSTER_COLORS)] if c != -1 else "#AAAAAA"
            axes[0].scatter(
                sub["pca_x"],
                sub["pca_y"],
                c=col,
                label=label,
                s=80,
                alpha=0.85,
                edgecolors="white",
                lw=0.5,
            )
        axes[0].set_xlabel("PC 1")
        axes[0].set_ylabel("PC 2")
        axes[0].set_title(f"{title}\nPCA Projection (coloured by cluster)")
        axes[0].legend(fontsize=9)
        sil = ev.get("silhouette", "N/A")
        db = ev.get("davies_bouldin", "N/A")
        axes[0].text(
            0.02,
            0.97,
            f"Silhouette={sil}  DB={db}",
            transform=axes[0].transAxes,
            va="top",
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.8),
        )

        for region, sub in df.groupby("region"):
            axes[1].scatter(
                sub["pca_x"],
                sub["pca_y"],
                c=PALETTE.get(region, "#888888"),
                label=region.replace("_", " ").capitalize(),
                s=80,
                alpha=0.85,
                edgecolors="white",
                lw=0.5,
            )
        axes[1].set_xlabel("PC 1")
        axes[1].set_ylabel("PC 2")
        axes[1].set_title("Same Projection\nColoured by True Region")
        axes[1].legend(fontsize=9)

        fig.suptitle(f"Clustering Results: {title}", fontsize=13, fontweight="bold")
        plt.tight_layout()
        paths.append(_save(fig, fname))
    return paths


def fig_k_sweep(results: dict):
    k_df = results.get("k_sweep")
    if k_df is None:
        return None
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    metrics_labels = [
        ("silhouette", "Silhouette Score", "Higher is better", True),
        ("davies_bouldin", "Davies-Bouldin Index", "Lower is better", False),
        ("calinski_harabasz", "Calinski-Harabasz Score", "Higher is better", True),
    ]
    for ax, (col, ylabel, note, higher) in zip(axes, metrics_labels):
        ax.plot(k_df["k"], k_df[col], marker="o", color="#2196F3", lw=2)
        best_k = k_df.loc[k_df[col].idxmax() if higher else k_df[col].idxmin(), "k"]
        ax.axvline(best_k, color="red", ls="--", lw=1.2, label=f"Optimal k={best_k}")
        ax.set_xlabel("Number of clusters k")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{ylabel}\n({note})")
        ax.legend(fontsize=9)
        ax.set_xticks(k_df["k"])
    fig.suptitle("K-Means: Optimal k Selection (Route-Level Features)", fontsize=13)
    plt.tight_layout()
    return _save(fig, "fig7_k_sweep_metrics.png")


def fig_cluster_profiles(results: dict, algo: str = "KMeans"):
    if algo not in results:
        return None
    df = results[algo]["data"]
    feat_cols = [
        "mean_delay",
        "cancellation_rate",
        "on_time_rate",
        "p85_delay",
        "std_delay",
    ]
    profile = df.groupby("cluster")[feat_cols].mean()

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(feat_cols))
    width = 0.18
    for i, (c, row) in enumerate(profile.iterrows()):
        label = f"Cluster {c}" if c != -1 else "Noise"
        col = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
        vals = row.values

        norm = (vals - profile.values.min(axis=0)) / (
            profile.values.max(axis=0) - profile.values.min(axis=0) + 1e-9
        )
        ax.bar(x + i * width, norm, width, label=label, color=col, alpha=0.85)

    ax.set_xticks(x + width * (len(profile) - 1) / 2)
    ax.set_xticklabels(
        ["Mean Delay", "Cancel Rate", "On-Time Rate", "P85 Delay", "Std Dev"],
        rotation=20,
        ha="right",
    )
    ax.set_ylabel("Normalised score (0=best, 1=worst for delay metrics)")
    ax.set_title(
        f"Cluster Reliability Profiles ({algo}, k=4)\n" "Normalised feature comparison"
    )
    ax.legend()
    return _save(fig, "fig8_cluster_profiles.png")


def fig_stop_map(conn: sqlite3.Connection, results: dict, algo: str = "KMeans"):
    try:
        import folium
    except ImportError:
        print("  [viz] folium not installed, skipping map.")
        return None

    stop_df = results[algo]["data"].copy() if algo in results else None
    if stop_df is None:
        return None

    stop_metrics = pd.read_sql(
        "SELECT m.entity_id AS stop_id, m.mean_delay, m.cancellation_rate, "
        "       s.stop_lat, s.stop_lon, s.zone_id AS region "
        "FROM reliability_metrics m JOIN stops s ON m.entity_id=s.stop_id "
        "WHERE m.aggregation_level='stop' AND m.mean_delay IS NOT NULL",
        conn,
    )

    stop_metrics["delay_quintile"] = pd.qcut(
        stop_metrics["mean_delay"], 5, labels=[1, 2, 3, 4, 5]
    )
    quintile_colors = {
        1: "#1a9850",
        2: "#91cf60",
        3: "#ffffbf",
        4: "#fc8d59",
        5: "#d73027",
    }

    m = folium.Map(location=[53.34, -6.27], zoom_start=11, tiles="CartoDB positron")

    for _, row in stop_metrics.iterrows():
        q = row["delay_quintile"]
        color = quintile_colors.get(q, "#888888")
        folium.CircleMarker(
            location=[row["stop_lat"], row["stop_lon"]],
            radius=4,
            color=color,
            fill=True,
            fill_opacity=0.75,
            popup=(
                f"Stop: {row['stop_id']}<br>"
                f"Region: {row['region']}<br>"
                f"Mean delay: {row['mean_delay']:.0f}s<br>"
                f"Cancel: {row['cancellation_rate']:.1%}"
            ),
        ).add_to(m)

    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:999;
                background:white;padding:10px;border-radius:6px;font-size:12px;">
    <b>Mean Delay Quintile</b><br>
    <span style="color:#1a9850">●</span> Q1 (best)<br>
    <span style="color:#91cf60">●</span> Q2<br>
    <span style="color:#ffffbf">●</span> Q3<br>
    <span style="color:#fc8d59">●</span> Q4<br>
    <span style="color:#d73027">●</span> Q5 (worst)
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))

    path = RESULTS_DIR / "fig9_stop_reliability_map.html"
    m.save(str(path))
    print(f"  [viz] Saved {path.name}")
    return path


def fig_aggregation_comparison(conn: sqlite3.Connection):
    """Show how mean delay ranking differs at stop vs route vs region level."""
    metrics = pd.read_sql(
        "SELECT m.aggregation_level, m.entity_id, m.mean_delay, "
        "       m.cancellation_rate, m.on_time_rate "
        "FROM reliability_metrics m "
        "WHERE m.mean_delay IS NOT NULL",
        conn,
    )

    fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=False)
    level_labels = {
        "stop": "Stop-Level",
        "route": "Route-Level",
        "region": "Region-Level",
    }

    for ax, level in zip(axes, ["stop", "route", "region"]):
        sub = metrics[metrics["aggregation_level"] == level]["mean_delay"]
        ax.hist(sub, bins=30, color="#2196F3", edgecolor="white", alpha=0.85)
        ax.axvline(
            sub.mean(), color="red", ls="--", lw=1.5, label=f"Mean={sub.mean():.0f}s"
        )
        ax.set_title(f"{level_labels[level]}\n(n={len(sub)})")
        ax.set_xlabel("Mean Delay (seconds)")
        ax.set_ylabel("Frequency")
        ax.legend(fontsize=9)

    fig.suptitle(
        "Distribution of Mean Delay Across Aggregation Levels\n"
        "(Research Question 3)",
        fontsize=13,
        fontweight="bold",
    )
    plt.tight_layout()
    return _save(fig, "fig10_aggregation_comparison.png")


def fig_temporal_cluster_profiles(temporal_df: pd.DataFrame, cluster_map: pd.DataFrame) -> Path:
    """Fig 11: Mean delay and on-time rate per DBSCAN cluster across time windows."""
    from temporal_stability import WINDOW_ORDER, cluster_window_profiles

    agg = cluster_window_profiles(temporal_df, cluster_map)
    present = [w for w in WINDOW_ORDER if w in agg["window_short"].values]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for c in sorted(agg.cluster.unique()):
        sub = agg[agg.cluster == c].set_index("window_short").reindex(present)
        n = int(sub["n_routes"].median())
        col = CLUSTER_COLORS[int(c) % len(CLUSTER_COLORS)]
        axes[0].plot(present, sub["mean_delay"], marker="o", lw=2.2, color=col,
                     label=f"Cluster {c}  (n≈{n})")
        axes[1].plot(present, sub["on_time_rate"] * 100, marker="o", lw=2.2, color=col,
                     label=f"Cluster {c}")

    for ax, (ylabel, title) in zip(axes, [
        ("Mean Delay (s)",    "Mean Delay per Cluster across Windows"),
        ("On-Time Rate (%)",  "On-Time Rate per Cluster across Windows"),
    ]):
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=9)
        ax.tick_params(axis="x", rotation=15)

    fig.suptitle("Fig 11: Temporal Stability — DBSCAN Cluster Profiles Across Windows",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    return _save(fig, "fig11_temporal_cluster_profiles.png")


def fig_route_stability_heatmap(
    temporal_df: pd.DataFrame, cluster_map: pd.DataFrame, top_n: int = 40
) -> Path:
    """Fig 12: Route × window heatmap sorted by volatility (CV)."""
    merged = temporal_df.merge(
        cluster_map[["route_id", "route_short_name"]], on="route_id", how="left"
    )
    from temporal_stability import WINDOW_ORDER

    present = [w for w in WINDOW_ORDER if w in merged["window_short"].values]
    pivot = merged.pivot_table(index="route_id", columns="window_short", values="mean_delay")
    pivot = pivot.reindex(columns=present).dropna(thresh=2)

    pivot_cv = pivot.std(axis=1) / (pivot.mean(axis=1).abs() + 1e-9)
    pivot = pivot.loc[pivot_cv.nlargest(top_n).index]

    # Normalise: deviation from each route's own mean (fractional)
    row_mean = pivot.mean(axis=1)
    pivot_norm = pivot.sub(row_mean, axis=0).div(row_mean.abs() + 1e-9, axis=0)

    name_map = cluster_map.set_index("route_id")["route_short_name"].to_dict()
    pivot_norm.index = [name_map.get(r, r[-8:]) for r in pivot_norm.index]

    fig, ax = plt.subplots(figsize=(7, 11))
    sns.heatmap(
        pivot_norm,
        cmap="RdYlGn_r",
        center=0,
        linewidths=0.3,
        cbar_kws={"label": "Relative change from route mean (red=worse, green=better)"},
        ax=ax,
    )
    ax.set_xlabel("Time Window")
    ax.set_ylabel("Route  (most volatile at top)")
    ax.set_title(
        f"Fig 12: Route Stability Heatmap\n(top {top_n} most volatile routes)",
        fontweight="bold",
    )
    plt.tight_layout()
    return _save(fig, "fig12_route_stability_heatmap.png")


def fig_stability_by_cluster(temporal_df: pd.DataFrame, cluster_map: pd.DataFrame) -> Path:
    """Fig 13: Boxplot of route CV (stability score) per DBSCAN cluster."""
    from temporal_stability import compute_stability_scores

    merged = temporal_df.merge(cluster_map[["route_id", "cluster"]], on="route_id", how="inner")
    merged = merged[merged.cluster != -1]
    scores = compute_stability_scores(merged)
    scores = scores.merge(cluster_map[["route_id", "cluster"]], on="route_id", how="left")
    scores = scores[scores.n_windows >= 2]

    clusters = sorted(scores.cluster.unique())
    data = [scores[scores.cluster == c]["cv"].values for c in clusters]

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(data, patch_artist=True, labels=[f"Cluster {c}" for c in clusters])
    for patch, c in zip(bp["boxes"], clusters):
        patch.set_facecolor(CLUSTER_COLORS[int(c) % len(CLUSTER_COLORS)])
        patch.set_alpha(0.75)
    ax.axhline(
        scores["cv"].median(), color="black", ls="--", lw=1.2, alpha=0.6,
        label=f"Fleet median CV = {scores['cv'].median():.2f}",
    )
    ax.set_ylabel("Coefficient of Variation  (lower = more stable)")
    ax.set_title(
        "Fig 13: Route Stability Score by Cluster\n"
        "(CV of mean_delay across time windows)",
        fontweight="bold",
    )
    ax.legend()
    plt.tight_layout()
    return _save(fig, "fig13_stability_by_cluster.png")


def fig_thu_vs_fri(temporal_df: pd.DataFrame, cluster_map: pd.DataFrame) -> Path | None:
    """Fig 14: Thu AM vs Fri Rush mean delay per route (scatter)."""
    thu = temporal_df[temporal_df.window_short == "Thu AM"][["route_id", "mean_delay"]].copy()
    fri = temporal_df[temporal_df.window_short == "Fri Rush"][["route_id", "mean_delay"]].copy()
    if fri.empty:
        print("  [viz] No Friday morning data — skipping Fig 14.")
        return None

    cmp = thu.merge(fri, on="route_id", suffixes=("_thu", "_fri"))
    cmp = cmp.merge(cluster_map[["route_id", "cluster"]], on="route_id", how="left")

    lo = min(cmp[["mean_delay_thu", "mean_delay_fri"]].min())
    hi = max(cmp[["mean_delay_thu", "mean_delay_fri"]].max())

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot([lo, hi], [lo, hi], "k--", lw=1.2, alpha=0.4, label="No change")
    for c in sorted(cmp.cluster.dropna().unique()):
        if c == -1:
            continue
        sub = cmp[cmp.cluster == c]
        ax.scatter(sub.mean_delay_thu, sub.mean_delay_fri,
                   c=CLUSTER_COLORS[int(c) % len(CLUSTER_COLORS)],
                   label=f"Cluster {c}  (n={len(sub)})",
                   s=80, alpha=0.82, edgecolors="white", lw=0.5)

    n_worse  = (cmp.mean_delay_fri > cmp.mean_delay_thu).sum()
    n_better = (cmp.mean_delay_fri < cmp.mean_delay_thu).sum()
    ax.text(0.03, 0.97, f"Worse on Fri: {n_worse}\nBetter on Fri: {n_better}",
            transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.85))
    ax.set_xlabel("Mean Delay — Thu Overnight/Morning (s)")
    ax.set_ylabel("Mean Delay — Fri Morning Rush (s)")
    ax.set_title("Fig 14: Thu Morning vs Fri Morning Rush\nPer-Route Mean Delay Comparison",
                 fontweight="bold")
    ax.legend(fontsize=9)
    plt.tight_layout()
    return _save(fig, "fig14_thu_vs_fri.png")


def generate_all_figures(
    conn: sqlite3.Connection,
    results: dict,
    temporal_df: pd.DataFrame | None = None,
    cluster_map: pd.DataFrame | None = None,
) -> list:
    print("\n[viz] Generating all figures …")
    paths = []
    paths.append(fig_delay_distributions(conn))
    paths.append(fig_cancellation_rates(conn))
    paths.append(fig_route_heatmap(conn))
    paths.extend(fig_clustering_scatter(results))
    paths.append(fig_k_sweep(results))
    paths.append(fig_cluster_profiles(results))
    paths.append(fig_stop_map(conn, results))
    paths.append(fig_aggregation_comparison(conn))

    if temporal_df is not None and cluster_map is not None and not temporal_df.empty:
        print("\n[viz] Generating temporal stability figures …")
        paths.append(fig_temporal_cluster_profiles(temporal_df, cluster_map))
        paths.append(fig_route_stability_heatmap(temporal_df, cluster_map))
        paths.append(fig_stability_by_cluster(temporal_df, cluster_map))
        paths.append(fig_thu_vs_fri(temporal_df, cluster_map))

    return [p for p in paths if p is not None]


if __name__ == "__main__":
    from clustering import run_all_clustering

    with get_connection() as conn:
        results = run_all_clustering(conn)
        generate_all_figures(conn, results)
