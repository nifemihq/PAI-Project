import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

REGION_BOXES = [
    ("city_centre", 53.328, 53.358, -6.285, -6.235),
    ("south_dublin", 53.240, 53.328, -6.320, -6.100),
    ("north_dublin", 53.358, 53.460, -6.300, -6.080),
    ("west_dublin", 53.300, 53.420, -6.480, -6.285),
    ("county_dublin", 53.240, 53.460, -6.480, -6.080),
]

DELAY_MIN = -600
DELAY_MAX = 5400


def assign_regions(conn: sqlite3.Connection) -> int:
    """
    Create a stop_regions table mapping stop_id → region label
    based on lat/lon bounding boxes.
    """
    stops = pd.read_sql(
        "SELECT stop_id, stop_lat, stop_lon FROM stops "
        "WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL",
        conn,
    )

    if stops.empty:
        print(
            "[cleaning] WARNING: stops table is empty — run gtfs_static_loader first."
        )
        return 0

    def assign(row):
        for region, lat_min, lat_max, lon_min, lon_max in REGION_BOXES:
            if (
                lat_min <= row.stop_lat <= lat_max
                and lon_min <= row.stop_lon <= lon_max
            ):
                return region
        return "other"

    stops["region"] = stops.apply(assign, axis=1)

    # Write to DB
    stops[["stop_id", "region"]].to_sql(
        "stop_regions", conn, if_exists="replace", index=False
    )
    conn.commit()

    dist = stops["region"].value_counts()
    print("[cleaning] Region assignment complete:")
    for region, count in dist.items():
        print(f"  {region:20s}: {count:,} stops")
    return len(stops)


def report_data_quality(conn: sqlite3.Connection) -> dict:
    """Print a data quality summary before cleaning."""
    total = conn.execute("SELECT COUNT(*) FROM delay_observations").fetchone()[0]
    null_both = conn.execute(
        "SELECT COUNT(*) FROM delay_observations "
        "WHERE trip_id IS NULL AND delay_seconds IS NULL"
    ).fetchone()[0]
    null_delay = conn.execute(
        "SELECT COUNT(*) FROM delay_observations "
        "WHERE delay_seconds IS NULL AND is_cancelled=0"
    ).fetchone()[0]
    cancelled = conn.execute(
        "SELECT COUNT(*) FROM delay_observations " "WHERE is_cancelled=1"
    ).fetchone()[0]
    extreme_high = conn.execute(
        f"SELECT COUNT(*) FROM delay_observations " f"WHERE delay_seconds > {DELAY_MAX}"
    ).fetchone()[0]
    extreme_low = conn.execute(
        f"SELECT COUNT(*) FROM delay_observations " f"WHERE delay_seconds < {DELAY_MIN}"
    ).fetchone()[0]

    print("\n[cleaning] ── Data Quality Report ──────────────────────")
    print(f"  Total rows:               {total:>10,}")
    print(
        f"  NULL trip_id + delay:     {null_both:>10,}  ({100*null_both/total:.1f}%) → will DROP"
    )
    print(
        f"  NULL delay (non-cancel):  {null_delay:>10,}  ({100*null_delay/total:.1f}%) → will DROP"
    )
    print(
        f"  Cancelled trips:          {cancelled:>10,}  ({100*cancelled/total:.1f}%) → keep (informative)"
    )
    print(
        f"  Delay > {DELAY_MAX}s (>{DELAY_MAX//60} min late): "
        f"{extreme_high:>10,}  ({100*extreme_high/total:.1f}%) → flag as outlier"
    )
    print(
        f"  Delay < {DELAY_MIN}s (>{abs(DELAY_MIN)//60} min early): "
        f"{extreme_low:>10,}  ({100*extreme_low/total:.1f}%) → flag as outlier"
    )
    print(f"──────────────────────────────────────────────────────")

    return {
        "total": total,
        "null_both": null_both,
        "null_delay": null_delay,
        "cancelled": cancelled,
        "extreme_high": extreme_high,
        "extreme_low": extreme_low,
    }


def clean_observations(conn: sqlite3.Connection) -> None:
    """
    Add an `is_outlier` column and a `is_valid` column to delay_observations.
    Does NOT delete rows — keeps full audit trail.
    Then creates a `delay_observations_clean` VIEW for use by the analysis.
    """
    existing = [
        r[1] for r in conn.execute("PRAGMA table_info(delay_observations)").fetchall()
    ]

    if "is_outlier" not in existing:
        conn.execute(
            "ALTER TABLE delay_observations ADD COLUMN is_outlier INTEGER DEFAULT 0"
        )

    if "is_valid" not in existing:
        conn.execute(
            "ALTER TABLE delay_observations ADD COLUMN is_valid INTEGER DEFAULT 1"
        )

    conn.execute(
        """
        UPDATE delay_observations
        SET is_valid = 0
        WHERE delay_seconds IS NULL AND is_cancelled = 0
    """
    )

    conn.execute(
        f"""
        UPDATE delay_observations
        SET is_outlier = 1
        WHERE delay_seconds > {DELAY_MAX} OR delay_seconds < {DELAY_MIN}
    """
    )

    conn.commit()

    conn.execute("DROP VIEW IF EXISTS delay_observations_clean")
    conn.execute(
        """
        CREATE VIEW delay_observations_clean AS
        SELECT
            o.*,
            COALESCE(sr.region, 'unknown') AS region
        FROM delay_observations o
        LEFT JOIN stop_regions sr ON o.stop_id = sr.stop_id
        WHERE o.is_valid = 1
          AND o.is_outlier = 0
    """
    )
    conn.commit()

    # Summary
    clean_count = conn.execute(
        "SELECT COUNT(*) FROM delay_observations_clean"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM delay_observations").fetchone()[0]
    print(
        f"\n[cleaning] Clean view created: {clean_count:,} / {total:,} rows "
        f"({100*clean_count/total:.1f}% retained)"
    )
    print("[cleaning] Use delay_observations_clean in all analysis queries.")


def verify_region_coverage(conn: sqlite3.Connection) -> None:
    """Check what % of observations have a known region after cleaning."""
    result = conn.execute(
        """
        SELECT region, COUNT(*) as n
        FROM delay_observations_clean
        GROUP BY region
        ORDER BY n DESC
    """
    ).fetchall()

    total = sum(r[1] for r in result)
    print("\n[cleaning] ── Observations by region (clean data) ───────")
    for region, n in result:
        print(f"  {(region or 'NULL'):20s}: {n:>10,}  ({100*n/total:.1f}%)")
    print("──────────────────────────────────────────────────────")


def run_cleaning() -> None:
    conn = get_connection()

    print("[cleaning] Step 1: Assigning geographic regions to stops …")
    n_stops = assign_regions(conn)

    if n_stops == 0:
        print(
            "[cleaning] Cannot continue without stops data. "
            "Run gtfs_static_loader.py first."
        )
        conn.close()
        return

    print("\n[cleaning] Step 2: Data quality report …")
    report_data_quality(conn)

    print("\n[cleaning] Step 3: Flagging invalid rows and outliers …")
    clean_observations(conn)

    print("\n[cleaning] Step 4: Verifying region coverage …")
    verify_region_coverage(conn)

    conn.close()
    print("\n[cleaning] Done. You can now run the analysis pipeline.")


if __name__ == "__main__":
    run_cleaning()
