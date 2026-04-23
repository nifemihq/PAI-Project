import sqlite3
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
from sklearn.metrics import (
    silhouette_score,
    davies_bouldin_score,
    calinski_harabasz_score,
)
from sklearn.decomposition import PCA
from database import get_connection

FEATURE_COLS = [
    "mean_delay",
    "median_delay",
    "p85_delay",
    "p95_delay",
    "std_delay",
    "on_time_rate",
    "cancellation_rate",
    "excess_wait_time",
]

MIN_OBS = 50


def load_route_features(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT * FROM reliability_metrics WHERE aggregation_level='route'", conn
    )
    df = df.dropna(subset=FEATURE_COLS)

    before = len(df)
    df = df[df["n_observations"] >= MIN_OBS]
    print(
        f"[clustering] Routes after min_obs={MIN_OBS} filter: "
        f"{len(df)} / {before} (dropped {before - len(df)} low-data routes)"
    )

    routes = pd.read_sql("SELECT route_id, route_short_name FROM routes", conn)

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

    raw = pd.read_sql(
        f"""
        SELECT route_id, region, COUNT(*) as cnt
        FROM {source}
        WHERE region NOT IN ('other', 'county_dublin', 'unknown', '')
          AND route_id IS NOT NULL
        GROUP BY route_id, region
    """,
        conn,
    )

    if not raw.empty:
        region_map = raw.sort_values("cnt", ascending=False).drop_duplicates(
            subset="route_id"
        )[["route_id", "region"]]
    else:
        region_map = pd.DataFrame(columns=["route_id", "region"])

    routes = routes.merge(region_map, on="route_id", how="left")
    routes["region"] = routes["region"].fillna("unknown")

    df = df.merge(
        routes[["route_id", "route_short_name", "region"]],
        left_on="entity_id",
        right_on="route_id",
        how="left",
    )
    df["region"] = df["region"].fillna("unknown")

    df["route_label"] = df["route_short_name"].where(
        df["route_short_name"].notna() & (df["route_short_name"] != ""), df["entity_id"]
    )

    n_with_region = (df["region"] != "unknown").sum()
    print(f"[clustering] Routes with region assigned: " f"{n_with_region} / {len(df)}")
    return df


def prepare_features(df: pd.DataFrame) -> tuple:
    X = df[FEATURE_COLS].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    return X_scaled, scaler


def evaluate_clustering(X: np.ndarray, labels: np.ndarray) -> dict:
    mask = labels != -1
    n_clusters = len(set(labels[mask]))
    if n_clusters < 2:
        return {
            "silhouette": None,
            "davies_bouldin": None,
            "calinski_harabasz": None,
            "n_clusters": n_clusters,
            "n_noise": int((labels == -1).sum()),
        }
    return {
        "n_clusters": n_clusters,
        "silhouette": round(silhouette_score(X[mask], labels[mask]), 4),
        "davies_bouldin": round(davies_bouldin_score(X[mask], labels[mask]), 4),
        "calinski_harabasz": round(calinski_harabasz_score(X[mask], labels[mask]), 4),
        "n_noise": int((labels == -1).sum()),
    }


def run_kmeans(X: np.ndarray, k: int = 4) -> np.ndarray:
    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    return model.fit_predict(X)


def run_agglomerative(X: np.ndarray, k: int = 4) -> np.ndarray:
    model = AgglomerativeClustering(n_clusters=k, linkage="ward")
    return model.fit_predict(X)


def run_dbscan(X: np.ndarray, eps: float = None, min_samples: int = 3) -> np.ndarray:
    """Auto-tune eps using the k-distance elbow method if not specified."""
    if eps is None:
        from sklearn.neighbors import NearestNeighbors

        nbrs = NearestNeighbors(n_neighbors=min_samples).fit(X)
        distances, _ = nbrs.kneighbors(X)
        k_distances = np.sort(distances[:, -1])
        eps = float(np.percentile(k_distances, 90))
        print(f"[clustering] DBSCAN auto-tuned eps={eps:.3f}")
    model = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean")
    return model.fit_predict(X)


def find_optimal_k(X: np.ndarray, k_range: range = range(2, 8)) -> pd.DataFrame:
    rows = []
    for k in k_range:
        labels = run_kmeans(X, k)
        ev = evaluate_clustering(X, labels)
        ev["k"] = k
        rows.append(ev)
    return pd.DataFrame(rows)


def run_all_clustering(conn: sqlite3.Connection) -> dict:
    route_df = load_route_features(conn)
    X, scaler = prepare_features(route_df)

    for i in range(X.shape[1]):
        cap = np.percentile(X[:, i], 99)
        floor = np.percentile(X[:, i], 1)
        X[:, i] = np.clip(X[:, i], floor, cap)
    print(f"[clustering] Features capped at 1st/99th percentile")

    pca = PCA(n_components=2, random_state=42)
    X_2d = pca.fit_transform(X)
    print(
        f"[clustering] PCA variance explained: "
        f"{pca.explained_variance_ratio_.cumsum()[1]:.1%} by 2 components"
    )

    results = {}

    for name, labels in [
        ("KMeans", run_kmeans(X, k=4)),
        ("Agglomerative", run_agglomerative(X, k=4)),
        ("DBSCAN", run_dbscan(X)),
    ]:
        ev = evaluate_clustering(X, labels)
        df_out = route_df.copy()
        df_out["cluster"] = labels
        df_out["pca_x"] = X_2d[:, 0]
        df_out["pca_y"] = X_2d[:, 1]
        results[name] = {"data": df_out, "eval": ev}
        print(
            f"[clustering] {name:15s} | k={ev.get('n_clusters','?')} "
            f"| sil={ev.get('silhouette','?')} "
            f"| DB={ev.get('davies_bouldin','?')} "
            f"| CH={ev.get('calinski_harabasz','?')} "
            f"| noise={ev.get('n_noise', 0)}"
        )

    results["k_sweep"] = find_optimal_k(X)
    return results


if __name__ == "__main__":
    with get_connection() as conn:
        results = run_all_clustering(conn)
