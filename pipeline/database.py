import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "dublin_bus.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def initialise_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't already exist."""
    ddl = """
    -- GTFS Static tables -------------------------------------------------
    CREATE TABLE IF NOT EXISTS routes (
        route_id        TEXT PRIMARY KEY,
        route_short_name TEXT,
        route_long_name  TEXT,
        route_type       INTEGER,
        agency_id        TEXT
    );

    CREATE TABLE IF NOT EXISTS stops (
        stop_id   TEXT PRIMARY KEY,
        stop_name TEXT,
        stop_lat  REAL,
        stop_lon  REAL,
        zone_id   TEXT
    );

    CREATE TABLE IF NOT EXISTS trips (
        trip_id    TEXT PRIMARY KEY,
        route_id   TEXT REFERENCES routes(route_id),
        service_id TEXT,
        direction_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS stop_times (
        trip_id        TEXT REFERENCES trips(trip_id),
        stop_id        TEXT REFERENCES stops(stop_id),
        stop_sequence  INTEGER,
        scheduled_arrival TEXT,
        PRIMARY KEY (trip_id, stop_sequence)
    );

    -- Live observation table (populated by GTFS-RT polling) ---------------
        CREATE TABLE IF NOT EXISTS delay_observations (
        obs_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        collected_at    TEXT NOT NULL,
        trip_id         TEXT,
        route_id        TEXT,
        stop_id         TEXT,
        stop_sequence   INTEGER,
        delay_seconds   REAL,
        is_cancelled    INTEGER DEFAULT 0,
        vehicle_id      TEXT,
        is_outlier      INTEGER DEFAULT 0,
        is_valid        INTEGER DEFAULT 1,
        region          TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_obs_route   ON delay_observations(route_id);
    CREATE INDEX IF NOT EXISTS idx_obs_stop    ON delay_observations(stop_id);
    CREATE INDEX IF NOT EXISTS idx_obs_time    ON delay_observations(collected_at);
    CREATE INDEX IF NOT EXISTS idx_obs_cancel  ON delay_observations(is_cancelled);
    CREATE INDEX IF NOT EXISTS idx_obs_outlier ON delay_observations(is_outlier);
    CREATE INDEX IF NOT EXISTS idx_obs_valid   ON delay_observations(is_valid);
    CREATE INDEX IF NOT EXISTS idx_obs_region  ON delay_observations(region);

    -- Aggregated reliability metrics table --------------------------------
    CREATE TABLE IF NOT EXISTS reliability_metrics (
        metric_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        aggregation_level TEXT NOT NULL,        -- 'stop' | 'route' | 'region'
        entity_id        TEXT NOT NULL,         -- stop_id / route_id / region_label
        window_start     TEXT,
        window_end       TEXT,
        n_observations   INTEGER,
        mean_delay       REAL,
        median_delay     REAL,
        p85_delay        REAL,
        p95_delay        REAL,
        std_delay        REAL,
        on_time_rate     REAL,                  -- fraction with |delay| <= 60s
        cancellation_rate REAL,
        excess_wait_time REAL                   -- EWT proxy
    );
    """
    conn.executescript(ddl)
    conn.commit()
    print("[database] Schema initialised.")


if __name__ == "__main__":
    with get_connection() as conn:
        initialise_schema(conn)
