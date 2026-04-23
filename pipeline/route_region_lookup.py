import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

ROUTE_REGION_MAP = {
    # City Centre
    "6": "city_centre",
    "82": "city_centre",
    "L12": "south_dublin",
    "L14": "south_dublin",
    "L89": "south_dublin",
    "1": "city_centre",
    "2": "city_centre",
    "7": "city_centre",
    "7A": "city_centre",
    "7B": "city_centre",
    "7D": "city_centre",
    "7N": "city_centre",
    "9": "city_centre",
    "11": "city_centre",
    "13": "city_centre",
    "16": "city_centre",
    "25": "city_centre",
    "25A": "city_centre",
    "25B": "city_centre",
    "25D": "city_centre",
    "25X": "city_centre",
    "26": "city_centre",
    "46": "city_centre",
    "49": "city_centre",
    "54A": "city_centre",
    "56A": "city_centre",
    "63": "city_centre",
    "79": "city_centre",
    "79A": "city_centre",
    "83": "city_centre",
    "83A": "city_centre",
    "F1": "city_centre",
    "N16": "city_centre",
    # North Dublin
    "14": "north_dublin",
    "14A": "north_dublin",
    "17": "north_dublin",
    "17A": "north_dublin",
    "27": "north_dublin",
    "27B": "north_dublin",
    "27X": "north_dublin",
    "29A": "north_dublin",
    "31": "north_dublin",
    "31A": "north_dublin",
    "31B": "north_dublin",
    "32": "north_dublin",
    "32A": "north_dublin",
    "32B": "north_dublin",
    "32X": "north_dublin",
    "33": "north_dublin",
    "33A": "north_dublin",
    "33B": "north_dublin",
    "33D": "north_dublin",
    "33X": "north_dublin",
    "41": "north_dublin",
    "41A": "north_dublin",
    "41B": "north_dublin",
    "41C": "north_dublin",
    "41D": "north_dublin",
    "41X": "north_dublin",
    "42": "north_dublin",
    "42A": "north_dublin",
    "42B": "north_dublin",
    "43": "north_dublin",
    "102": "north_dublin",
    "104": "north_dublin",
    "105": "north_dublin",
    "106": "north_dublin",
    "108": "north_dublin",
    "109": "north_dublin",
    "130": "north_dublin",
    "142": "north_dublin",
    "H1": "north_dublin",
    "H2": "north_dublin",
    "H3": "north_dublin",
    "H4": "north_dublin",
    "N4": "north_dublin",
    "N29": "north_dublin",
    "N32": "north_dublin",
    "N41": "north_dublin",
    # South Dublin
    "4": "south_dublin",
    "8": "south_dublin",
    "15": "south_dublin",
    "15A": "south_dublin",
    "15B": "south_dublin",
    "15D": "south_dublin",
    "15E": "south_dublin",
    "15F": "south_dublin",
    "18": "south_dublin",
    "19": "south_dublin",
    "19A": "south_dublin",
    "44": "south_dublin",
    "44B": "south_dublin",
    "45": "south_dublin",
    "45A": "south_dublin",
    "46A": "south_dublin",
    "46B": "south_dublin",
    "46E": "south_dublin",
    "47": "south_dublin",
    "58": "south_dublin",
    "59": "south_dublin",
    "61": "south_dublin",
    "62": "south_dublin",
    "64": "south_dublin",
    "64X": "south_dublin",
    "65": "south_dublin",
    "65B": "south_dublin",
    "68": "south_dublin",
    "68A": "south_dublin",
    "68X": "south_dublin",
    "69": "south_dublin",
    "69X": "south_dublin",
    "75": "south_dublin",
    "76": "south_dublin",
    "76A": "south_dublin",
    "84": "south_dublin",
    "84A": "south_dublin",
    "84X": "south_dublin",
    "111": "south_dublin",
    "114": "south_dublin",
    "116": "south_dublin",
    "118": "south_dublin",
    "145": "south_dublin",
    "175": "south_dublin",
    "184": "south_dublin",
    "185": "south_dublin",
    "C1": "south_dublin",
    "C2": "south_dublin",
    "C3": "south_dublin",
    "C4": "south_dublin",
    "N8": "south_dublin",
    "N44": "south_dublin",
    "N65": "south_dublin",
    # West Dublin
    "18A": "west_dublin",
    "37": "west_dublin",
    "37A": "west_dublin",
    "37B": "west_dublin",
    "38": "west_dublin",
    "38A": "west_dublin",
    "38B": "west_dublin",
    "38D": "west_dublin",
    "39": "west_dublin",
    "39A": "west_dublin",
    "39X": "west_dublin",
    "40": "west_dublin",
    "40A": "west_dublin",
    "40B": "west_dublin",
    "40C": "west_dublin",
    "40D": "west_dublin",
    "40E": "west_dublin",
    "51": "west_dublin",
    "51A": "west_dublin",
    "51B": "west_dublin",
    "51C": "west_dublin",
    "51D": "west_dublin",
    "51X": "west_dublin",
    "52": "west_dublin",
    "53": "west_dublin",
    "56": "west_dublin",
    "57": "west_dublin",
    "66": "west_dublin",
    "66A": "west_dublin",
    "66B": "west_dublin",
    "66X": "west_dublin",
    "67": "west_dublin",
    "67A": "west_dublin",
    "67X": "west_dublin",
    "70": "west_dublin",
    "71": "west_dublin",
    "72": "west_dublin",
    "74": "west_dublin",
    "77": "west_dublin",
    "77A": "west_dublin",
    "77X": "west_dublin",
    "120": "west_dublin",
    "121": "west_dublin",
    "122": "west_dublin",
    "123": "west_dublin",
    "124": "west_dublin",
    "125": "west_dublin",
    "126": "west_dublin",
    "127": "west_dublin",
    "128": "west_dublin",
    "129": "west_dublin",
    "150": "west_dublin",
    "151": "west_dublin",
    "155": "west_dublin",
    "161": "west_dublin",
    "210": "west_dublin",
    "220": "west_dublin",
    "236": "west_dublin",
    "239": "west_dublin",
    "250": "west_dublin",
    "251": "west_dublin",
    "270": "west_dublin",
    "E1": "west_dublin",
    "E2": "west_dublin",
    "F2": "west_dublin",
    "F3": "west_dublin",
    "G1": "west_dublin",
    "G2": "west_dublin",
    "S2": "west_dublin",
    "S4": "west_dublin",
    "S6": "west_dublin",
    "S8": "west_dublin",
    "L54": "west_dublin",
    "L55": "west_dublin",
    "L56": "west_dublin",
    "L57": "west_dublin",
    "L58": "west_dublin",
    "L59": "west_dublin",
    "N25": "west_dublin",
    "N26": "west_dublin",
    "N66": "west_dublin",
}

GOOD_REGIONS = {"city_centre", "south_dublin", "north_dublin", "west_dublin"}


def run_lookup() -> None:
    conn = get_connection()

    cols = [
        r[1] for r in conn.execute("PRAGMA table_info(delay_observations)").fetchall()
    ]
    if "region" not in cols:
        conn.execute("ALTER TABLE delay_observations ADD COLUMN region TEXT")
        conn.commit()
        print("[route_lookup] Added 'region' column to delay_observations")

    conn.execute(
        """
        UPDATE delay_observations
        SET region = (
            SELECT sr.region FROM stop_regions sr
            WHERE sr.stop_id = delay_observations.stop_id
              AND sr.region IN ('city_centre','south_dublin',
                                'north_dublin','west_dublin')
        )
        WHERE region IS NULL OR region NOT IN
              ('city_centre','south_dublin','north_dublin','west_dublin')
    """
    )
    conn.commit()
    n_coord = conn.execute(
        "SELECT COUNT(*) FROM delay_observations WHERE region IN "
        "('city_centre','south_dublin','north_dublin','west_dublin')"
    ).fetchone()[0]
    print(f"[route_lookup] Coordinate-based region: {n_coord:,} observations")

    # ── Step 3: Build route_id → region from short name lookup ───────────
    route_rows = conn.execute(
        "SELECT route_id, route_short_name FROM routes "
        "WHERE route_short_name IS NOT NULL AND route_short_name != ''"
    ).fetchall()

    route_id_to_region = {}
    for route_id, short_name in route_rows:
        region = ROUTE_REGION_MAP.get(short_name.strip())
        if region:
            route_id_to_region[route_id] = region

    print(
        f"[route_lookup] Route number lookup covers "
        f"{len(route_id_to_region)} route IDs"
    )

    updates = [(region, route_id) for route_id, region in route_id_to_region.items()]
    if updates:
        conn.executemany(
            """
            UPDATE delay_observations
            SET region = ?
            WHERE route_id = ?
              AND (region IS NULL OR region NOT IN
                   ('city_centre','south_dublin','north_dublin','west_dublin'))
        """,
            updates,
        )
        conn.commit()

    n_route = conn.execute(
        "SELECT COUNT(*) FROM delay_observations WHERE region IN "
        "('city_centre','south_dublin','north_dublin','west_dublin')"
    ).fetchone()[0]
    print(f"[route_lookup] After route lookup: {n_route:,} observations with region")

    conn.execute("DROP VIEW IF EXISTS delay_observations_clean")
    conn.execute(
        """
        CREATE VIEW delay_observations_clean AS
        SELECT *,
               COALESCE(region, 'unknown') AS effective_region
        FROM delay_observations
        WHERE is_valid   = 1
          AND is_outlier = 0
    """
    )
    conn.commit()

    conn.execute("DROP VIEW IF EXISTS delay_observations_clean")
    conn.execute(
        """
        CREATE VIEW delay_observations_clean AS
        SELECT
            obs_id, collected_at, trip_id, route_id, stop_id,
            stop_sequence, delay_seconds, is_cancelled, vehicle_id,
            is_outlier, is_valid,
            COALESCE(region, 'unknown') AS region
        FROM delay_observations
        WHERE is_valid   = 1
          AND is_outlier = 0
    """
    )
    conn.commit()

    result = conn.execute(
        """
        SELECT region, COUNT(*) as n
        FROM delay_observations_clean
        GROUP BY region ORDER BY n DESC
    """
    ).fetchall()

    total = sum(r[1] for r in result)
    print(f"\n[route_lookup] ── Region coverage ({total:,} clean rows) ─────")
    for region, n in result:
        print(f"  {(region or 'NULL'):20s}: {n:>10,}  ({100*n/total:.1f}%)")
    print("──────────────────────────────────────────────────────")
    conn.close()


if __name__ == "__main__":
    run_lookup()
