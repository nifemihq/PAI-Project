import sqlite3, numpy as np, pandas as pd, warnings
from sklearn.cluster import KMeans, AgglomerativeClustering, DBSCAN
from sklearn.metrics import (
    silhouette_score,
    davies_bouldin_score,
    calinski_harabasz_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")

conn = sqlite3.connect("data/dublin_bus.db")
pc = "route_id LIKE '5570_%'"

# ---------------------------------------------------------------------------
# 1. Route-level reliability metrics
# ---------------------------------------------------------------------------
df = pd.read_sql(
    f"SELECT route_id, delay_seconds, is_cancelled, is_outlier FROM delay_observations WHERE is_valid=1 AND ({pc})",
    conn,
)
clean = df[(df.is_outlier == 0) & (df.is_cancelled == 0) & df.delay_seconds.notna()]
m = (
    clean.groupby("route_id")["delay_seconds"]
    .agg(
        mean_delay="mean",
        median_delay="median",
        std_delay="std",
        p85_delay=lambda x: np.percentile(x, 85),
        p95_delay=lambda x: np.percentile(x, 95),
    )
    .reset_index()
)
ot = clean.copy()
ot["ot"] = ot.delay_seconds.abs() <= 60
m = m.merge(
    ot.groupby("route_id")["ot"]
    .mean()
    .reset_index()
    .rename(columns={"ot": "on_time_rate"}),
    on="route_id",
)
late = clean[clean.delay_seconds > 0]
ewt = late.groupby("route_id")["delay_seconds"].mean().reset_index()
ewt.columns = ["route_id", "ewt"]
ewt["ewt"] /= 60
m = m.merge(ewt, on="route_id", how="left")
tot = df.groupby("route_id").size().reset_index(name="n")
canc = df[df.is_cancelled == 1].groupby("route_id").size().reset_index(name="nc")
cr = tot.merge(canc, on="route_id", how="left").fillna(0)
cr["cancellation_rate"] = cr.nc / cr.n
m = m.merge(cr[["route_id", "cancellation_rate"]], on="route_id")

print(f"Total routes: {len(m)}")
print(f"Overall mean delay: {m.mean_delay.mean():.1f}s")
print(f"Overall on-time rate: {m.on_time_rate.mean()*100:.1f}%")
print(f"Delay range: {m.mean_delay.min():.1f}s to {m.mean_delay.max():.1f}s")
print(f"Overall cancellation rate: {m.cancellation_rate.mean()*100:.3f}%")

# ---------------------------------------------------------------------------
# 2. Region assignment
# ---------------------------------------------------------------------------
routes_static = pd.read_csv("data/gtfs_dublin_bus/routes.txt", dtype=str)[
    ["route_id", "route_short_name", "route_long_name"]
]
routes_static["route_short_name"] = (
    routes_static["route_short_name"].str.strip().str.upper()
)

NORTH = {
    "1",
    "2",
    "3",
    "11",
    "13X",
    "16",
    "16C",
    "17",
    "17A",
    "27",
    "27X",
    "29A",
    "31",
    "31A",
    "31B",
    "32",
    "32X",
    "33",
    "33X",
    "41",
    "41B",
    "41C",
    "41D",
    "41X",
    "42",
    "42D",
    "43",
    "44",
    "44B",
    "53",
    "83",
    "83A",
    "101",
    "102",
    "104",
    "109",
    "116",
    "120",
    "122",
    "123",
    "130",
    "142",
    "145",
}
SOUTH = {
    "7",
    "7A",
    "7B",
    "7D",
    "8",
    "14",
    "14C",
    "15",
    "15A",
    "15B",
    "44",
    "61",
    "63",
    "65",
    "65B",
    "68",
    "68A",
    "75",
    "77A",
    "77X",
    "84",
    "84A",
    "84X",
}
WEST = {
    "13",
    "25",
    "25A",
    "25B",
    "25D",
    "25X",
    "26",
    "37",
    "38",
    "38A",
    "39",
    "39A",
    "39X",
    "40",
    "40B",
    "40D",
    "51",
    "51B",
    "51D",
    "51X",
    "66",
    "66A",
    "66B",
    "66X",
    "67",
    "67X",
    "69",
    "69X",
    "70",
    "70X",
    "76",
    "76A",
    "79",
    "79A",
}
CITY = {
    "4",
    "9",
    "10",
    "46A",
    "47",
    "49",
    "54A",
    "56A",
    "65",
    "66",
    "67",
    "68",
    "68X",
    "145",
    "747",
    "757",
}


def assign_region(s):
    s = str(s).upper().strip()
    if s in CITY:
        return "City Centre"
    if s in NORTH:
        return "North Dublin"
    if s in SOUTH:
        return "South Dublin"
    if s in WEST:
        return "West Dublin"
    try:
        n = int("".join(c for c in s if c.isdigit()))
        if n <= 19:
            return "City Centre"
        if n <= 39:
            return "North Dublin"
        if n <= 69:
            return "West Dublin"
        if n <= 84:
            return "South Dublin"
        return "North Dublin"
    except:
        return "Unknown"


routes_static["region"] = routes_static["route_short_name"].apply(assign_region)
m2 = m.merge(
    routes_static[["route_id", "route_short_name", "region"]], on="route_id", how="left"
)
m2["region"] = m2["region"].fillna("Unknown")

reg = (
    m2[m2.region != "Unknown"]
    .groupby("region")
    .agg(
        mean_delay=("mean_delay", "mean"),
        on_time_rate=("on_time_rate", "mean"),
        cancellation_rate=("cancellation_rate", "mean"),
        n_routes=("route_id", "count"),
    )
    .reset_index()
    .sort_values("mean_delay")
)

print("\n=== REGIONAL BREAKDOWN ===")
for _, row in reg.iterrows():
    print(
        f"  {row['region']:15s}: mean={row['mean_delay']:.1f}s, on_time={row['on_time_rate']*100:.1f}%, cancel={row['cancellation_rate']*100:.3f}%, n={row['n_routes']}"
    )

FEATS = [
    "mean_delay",
    "median_delay",
    "p85_delay",
    "p95_delay",
    "std_delay",
    "on_time_rate",
    "cancellation_rate",
    "ewt",
]
cdf = m2.dropna(subset=FEATS).copy()
X = StandardScaler().fit_transform(cdf[FEATS].values)
print(f"\nRoutes for clustering: {len(cdf)}")


def ev(labels, X):
    mask = labels != -1
    if mask.sum() < 2 or len(set(labels[mask])) < 2:
        return None, None, None
    s = round(silhouette_score(X[mask], labels[mask]), 4)
    d = round(davies_bouldin_score(X[mask], labels[mask]), 4)
    c = round(calinski_harabasz_score(X[mask], labels[mask]), 2)
    return s, d, c


km_labels = KMeans(n_clusters=4, random_state=42, n_init=10).fit_predict(X)
ag_labels = AgglomerativeClustering(n_clusters=4, linkage="ward").fit_predict(X)

# DBSCAN — eps auto-tuned using 90th percentile of k-distances (consistent with pipeline)
nbrs = NearestNeighbors(n_neighbors=3).fit(X)
dists, _ = nbrs.kneighbors(X)
k_distances = np.sort(dists[:, -1])
eps = float(np.percentile(k_distances, 90))
db_labels = DBSCAN(eps=eps, min_samples=3).fit_predict(X)

print("\n=== CLUSTERING RESULTS ===")
for name, labels in [
    ("K-Means (k=4)", km_labels),
    ("Agglomerative Ward (k=4)", ag_labels),
    (f"DBSCAN (eps={eps:.3f})", db_labels),
]:
    s, d, c = ev(labels, X)
    nc = len(set(labels)) - (1 if -1 in labels else 0)
    noise = int((labels == -1).sum())
    print(f"  {name}: clusters={nc}, noise={noise}, silhouette={s}, DB={d}, CH={c}")

cdf2 = cdf.copy()
cdf2["cluster"] = db_labels
ndf = cdf2[cdf2.cluster != -1]
print(f"\n=== DBSCAN CLUSTER PROFILES (eps={eps:.3f}) ===")
prof = (
    ndf.groupby("cluster")[
        ["mean_delay", "median_delay", "on_time_rate", "cancellation_rate", "ewt"]
    ]
    .mean()
    .round(2)
)
for ci, row in prof.iterrows():
    n_routes = (ndf.cluster == ci).sum()
    print(
        f"  Cluster {ci} ({n_routes} routes): mean_delay={row['mean_delay']:.1f}s, on_time={row['on_time_rate']*100:.1f}%, cancel={row['cancellation_rate']*100:.3f}%, ewt={row['ewt']:.2f}min"
    )
print(f"  Noise: {int((db_labels == -1).sum())} routes")

rf_data = cdf2[cdf2.cluster != -1]
if len(rf_data["cluster"].unique()) >= 2:
    rf = RandomForestClassifier(
        n_estimators=500, random_state=42, class_weight="balanced"
    )
    rf.fit(rf_data[FEATS].values, rf_data["cluster"].values)
    imp = pd.Series(rf.feature_importances_, index=FEATS).sort_values(ascending=False)
    print("\n=== RF FEATURE IMPORTANCE ===")
    for f, v in imp.items():
        print(f"  {f:25s}: {v:.4f}")
else:
    print("\n=== RF FEATURE IMPORTANCE ===")
    print("  Skipped — DBSCAN produced fewer than 2 clusters for RF training.")

stop_df = pd.read_sql(
    f"SELECT stop_id, AVG(delay_seconds) as mean_delay, COUNT(*) as n FROM delay_observations "
    f"WHERE is_valid=1 AND is_outlier=0 AND is_cancelled=0 AND delay_seconds IS NOT NULL AND ({pc}) "
    f"GROUP BY stop_id HAVING n>=10",
    conn,
)
print(f"\n=== AGGREGATION LEVELS ===")
print(
    f"  Stop level:   n={len(stop_df)}, mean={stop_df.mean_delay.mean():.1f}s, std={stop_df.mean_delay.std():.1f}s, range={stop_df.mean_delay.min():.0f}–{stop_df.mean_delay.max():.0f}s"
)
print(
    f"  Route level:  n={len(m2)}, mean={m2.mean_delay.mean():.1f}s, std={m2.mean_delay.std():.1f}s, range={m2.mean_delay.min():.0f}–{m2.mean_delay.max():.0f}s"
)
print(
    f"  Region level: n={len(reg)}, mean={reg.mean_delay.mean():.1f}s, std={reg.mean_delay.std():.1f}s, range={reg.mean_delay.min():.1f}–{reg.mean_delay.max():.1f}s"
)

conn.close()
print("\nDone.")
