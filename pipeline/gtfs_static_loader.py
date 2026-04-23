import sys
import zipfile
import sqlite3
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection, initialise_schema

REQUIRED_FILES = ["routes.txt", "stops.txt", "trips.txt", "stop_times.txt"]
OPTIONAL_FILES = ["calendar.txt", "calendar_dates.txt", "shapes.txt"]


def _resolve_source(source: str) -> Path:
    """Return a directory path containing the .txt files, extracting zip if needed."""
    p = Path(source)
    if not p.exists():
        sys.exit(f"ERROR: '{source}' does not exist.")

    if p.is_dir():
        return p

    if p.suffix == ".zip":
        extract_to = p.parent / p.stem
        if not extract_to.exists():
            print(f"[loader] Extracting {p.name} → {extract_to}/")
            with zipfile.ZipFile(p, "r") as zf:
                zf.extractall(extract_to)
        else:
            print(f"[loader] Already extracted at {extract_to}/")
        return extract_to

    sys.exit(f"ERROR: '{source}' must be a directory or .zip file.")


def _check_files(folder: Path) -> None:
    missing = [f for f in REQUIRED_FILES if not (folder / f).exists()]
    if missing:
        sys.exit(f"ERROR: Missing required files in {folder}: {missing}")
    print(f"[loader] Found all required files in {folder}/")


def load_routes(folder: Path, conn: sqlite3.Connection) -> int:
    """Load routes.txt — filter to Dublin Bus (agency_id 'dublinbus' or '978')."""
    df = pd.read_csv(folder / "routes.txt", dtype=str).fillna("")

    if "agency_id" in df.columns:
        before = len(df)
        dublin_bus_ids = {"978", "dublinbus", "DublinBus", "DUBLIN_BUS"}
        df = df[df["agency_id"].isin(dublin_bus_ids)]
        if len(df) == 0:
            df = pd.read_csv(folder / "routes.txt", dtype=str).fillna("")
            print(
                f"[loader] No agency_id filter matched — loading all {len(df)} routes"
            )
        else:
            print(f"[loader] Filtered routes: {before} → {len(df)} (Dublin Bus only)")

    keep = [
        "route_id",
        "route_short_name",
        "route_long_name",
        "route_type",
        "agency_id",
    ]
    df = df[[c for c in keep if c in df.columns]]
    df.to_sql("routes", conn, if_exists="replace", index=False)
    conn.commit()
    print(f"[loader] routes: {len(df)} rows loaded")
    return len(df)


def load_stops(folder: Path, conn: sqlite3.Connection) -> int:
    """Load stops.txt — all stops (routes will filter later via joins)."""
    df = pd.read_csv(folder / "stops.txt", dtype=str).fillna("")

    df["stop_lat"] = pd.to_numeric(df.get("stop_lat", 0), errors="coerce")
    df["stop_lon"] = pd.to_numeric(df.get("stop_lon", 0), errors="coerce")

    keep = ["stop_id", "stop_name", "stop_lat", "stop_lon", "zone_id"]
    df = df[[c for c in keep if c in df.columns]]

    if "zone_id" not in df.columns:
        df["zone_id"] = ""

    df.to_sql("stops", conn, if_exists="replace", index=False)
    conn.commit()
    print(f"[loader] stops: {len(df)} rows loaded")
    return len(df)


def load_trips(folder: Path, conn: sqlite3.Connection) -> int:
    """Load trips.txt — only for routes already in our routes table."""
    route_ids = set(
        r[0] for r in conn.execute("SELECT route_id FROM routes").fetchall()
    )
    df = pd.read_csv(folder / "trips.txt", dtype=str).fillna("")
    before = len(df)
    df = df[df["route_id"].isin(route_ids)]

    keep = ["trip_id", "route_id", "service_id", "direction_id"]
    df = df[[c for c in keep if c in df.columns]]
    if "direction_id" not in df.columns:
        df["direction_id"] = 0

    df.to_sql("trips", conn, if_exists="replace", index=False)
    conn.commit()
    print(f"[loader] trips: {before} total → {len(df)} for our routes loaded")
    return len(df)


def load_stop_times(
    folder: Path, conn: sqlite3.Connection, chunksize: int = 100_000
) -> int:
    """
    Load stop_times.txt in chunks — this file is typically millions of rows.
    Only keeps rows for trip_ids already in our trips table.
    """
    trip_ids = set(r[0] for r in conn.execute("SELECT trip_id FROM trips").fetchall())
    print(f"[loader] stop_times: filtering to {len(trip_ids):,} trips (chunked read)…")

    total = 0
    for i, chunk in enumerate(
        pd.read_csv(folder / "stop_times.txt", dtype=str, chunksize=chunksize)
    ):

        chunk = chunk[chunk["trip_id"].isin(trip_ids)]
        if len(chunk) == 0:
            continue

        keep = ["trip_id", "stop_id", "stop_sequence", "arrival_time"]
        chunk = chunk[[c for c in keep if c in chunk.columns]]
        chunk = chunk.rename(columns={"arrival_time": "scheduled_arrival"})
        if "stop_sequence" in chunk.columns:
            chunk["stop_sequence"] = pd.to_numeric(
                chunk["stop_sequence"], errors="coerce"
            )

        chunk.to_sql(
            "stop_times",
            conn,
            if_exists="append" if total > 0 else "replace",
            index=False,
        )
        total += len(chunk)
        if (i + 1) % 10 == 0:
            print(f"  … {total:,} stop_time rows so far")

    conn.commit()
    print(f"[loader] stop_times: {total:,} rows loaded")
    return total


def load_all(source: str) -> None:
    folder = _resolve_source(source)
    _check_files(folder)

    conn = get_connection()
    initialise_schema(conn)

    n_routes = load_routes(folder, conn)
    n_stops = load_stops(folder, conn)
    n_trips = load_trips(folder, conn)
    n_stop_times = load_stop_times(folder, conn)

    print(f"\n[loader] ✓ Static load complete:")
    print(f"         {n_routes:,} routes")
    print(f"         {n_stops:,} stops")
    print(f"         {n_trips:,} trips")
    print(f"         {n_stop_times:,} stop_times")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python pipeline/gtfs_static_loader.py <path/to/gtfs_folder_or_zip>"
        )
        print("Example: python pipeline/gtfs_static_loader.py data/gtfs_static/")
        print(
            "Example: python pipeline/gtfs_static_loader.py data/google_transit_dublinbus.zip"
        )
        sys.exit(1)
    load_all(sys.argv[1])
