import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

DB_PATH = Path(__file__).parent / "data" / "dublin_bus.db"
LOG_PATH = Path(__file__).parent / "data" / "collection.log"
NTA_URL = "https://api.nationaltransport.ie/gtfsr/v2/gtfsr"
DUBLIN_BUS_PREFIX = "5570_"

# Outlier thresholds (kept in DB but excluded from metric computation)
MAX_DELAY_SECONDS = 90 * 60   # +90 minutes
MIN_DELAY_SECONDS = -10 * 60  # -10 minutes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def load_stop_region_map(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT stop_id, region FROM stop_regions").fetchall()
    return {stop_id: region for stop_id, region in rows}


def insert_observations(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO delay_observations
            (collected_at, trip_id, route_id, stop_id, stop_sequence,
             delay_seconds, is_cancelled, vehicle_id, is_outlier, is_valid, region)
        VALUES
            (:collected_at, :trip_id, :route_id, :stop_id, :stop_sequence,
             :delay_seconds, :is_cancelled, :vehicle_id, :is_outlier, :is_valid, :region)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def fetch_feed(api_key: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(
        NTA_URL,
        headers={"x-api-key": api_key, "Cache-Control": "no-cache"},
        timeout=30,
    )
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


SKIPPED_RELATIONSHIP = {1, 3}  # SKIPPED=1, NO_DATA=3 — no real-time signal


def parse_feed(
    feed: gtfs_realtime_pb2.FeedMessage,
    collected_at: str,
    stop_region: dict,
) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    stats = {"entities": len(feed.entity), "dublin_bus": 0, "rows": 0,
             "cancelled": 0, "outliers": 0, "invalid": 0}

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue

        tu = entity.trip_update
        trip_id = tu.trip.trip_id
        route_id = tu.trip.route_id

        if not route_id.startswith(DUBLIN_BUS_PREFIX):
            continue

        stats["dublin_bus"] += 1
        vehicle_id = tu.vehicle.id if tu.HasField("vehicle") else None

        for stu in tu.stop_time_update:
            stop_id = stu.stop_id
            stop_seq = stu.stop_sequence
            rel = stu.schedule_relationship

            # Rows with no delay and no cancellation flag carry no signal
            has_delay = stu.HasField("arrival") or stu.HasField("departure")
            is_cancelled = int(rel == 1)  # SKIPPED

            if not has_delay and not is_cancelled:
                stats["invalid"] += 1
                rows.append({
                    "collected_at": collected_at,
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "stop_id": stop_id,
                    "stop_sequence": stop_seq,
                    "delay_seconds": None,
                    "is_cancelled": 0,
                    "vehicle_id": vehicle_id,
                    "is_outlier": 0,
                    "is_valid": 0,
                    "region": stop_region.get(stop_id),
                })
                continue

            delay = None
            if stu.HasField("arrival") and stu.arrival.HasField("delay"):
                delay = float(stu.arrival.delay)
            elif stu.HasField("departure") and stu.departure.HasField("delay"):
                delay = float(stu.departure.delay)

            is_outlier = 0
            if delay is not None and (delay > MAX_DELAY_SECONDS or delay < MIN_DELAY_SECONDS):
                is_outlier = 1
                stats["outliers"] += 1

            if is_cancelled:
                stats["cancelled"] += 1

            rows.append({
                "collected_at": collected_at,
                "trip_id": trip_id,
                "route_id": route_id,
                "stop_id": stop_id,
                "stop_sequence": stop_seq,
                "delay_seconds": delay,
                "is_cancelled": is_cancelled,
                "vehicle_id": vehicle_id,
                "is_outlier": is_outlier,
                "is_valid": 1,
                "region": stop_region.get(stop_id),
            })
            stats["rows"] += 1

    return rows, stats


def run(api_key: str, duration_minutes: int, interval_seconds: int, label: str) -> None:
    conn = get_conn()
    stop_region = load_stop_region_map(conn)
    log.info(f"Loaded {len(stop_region):,} stop→region mappings from DB.")

    existing = conn.execute("SELECT COUNT(*) FROM delay_observations").fetchone()[0]
    log.info(f"Existing observations in DB: {existing:,}")

    deadline = time.monotonic() + duration_minutes * 60
    poll_num = 0
    total_inserted = 0
    consecutive_errors = 0
    label_str = f" [{label}]" if label else ""

    log.info(
        f"Starting collection{label_str}: duration={duration_minutes} min, "
        f"interval={interval_seconds} s — press Ctrl+C to stop early."
    )
    log.info("-" * 70)

    try:
        while time.monotonic() < deadline:
            poll_start = time.monotonic()
            poll_num += 1
            collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            remaining_min = (deadline - time.monotonic()) / 60

            try:
                feed = fetch_feed(api_key)
                rows, stats = parse_feed(feed, collected_at, stop_region)
                n = insert_observations(conn, rows)
                total_inserted += n
                consecutive_errors = 0

                log.info(
                    f"Poll {poll_num:4d} | {collected_at} | "
                    f"entities={stats['entities']:4d} | "
                    f"DB rows inserted={n:6,} | "
                    f"total={total_inserted:,} | "
                    f"~{remaining_min:.0f} min left"
                )

            except requests.HTTPError as exc:
                consecutive_errors += 1
                log.warning(f"Poll {poll_num}: HTTP error — {exc} (error #{consecutive_errors})")
                if consecutive_errors >= 5:
                    log.error("5 consecutive HTTP errors — stopping collection.")
                    break

            except requests.RequestException as exc:
                consecutive_errors += 1
                log.warning(f"Poll {poll_num}: Network error — {exc} (error #{consecutive_errors})")
                if consecutive_errors >= 10:
                    log.error("10 consecutive network errors — stopping collection.")
                    break

            elapsed = time.monotonic() - poll_start
            sleep_for = max(0, interval_seconds - elapsed)
            if sleep_for > 0 and time.monotonic() < deadline:
                time.sleep(sleep_for)

    except KeyboardInterrupt:
        log.info("Interrupted by user (Ctrl+C).")

    finally:
        final_count = conn.execute("SELECT COUNT(*) FROM delay_observations").fetchone()[0]
        log.info("-" * 70)
        log.info(f"Collection finished{label_str}.")
        log.info(f"Polls completed: {poll_num}")
        log.info(f"Rows inserted this run: {total_inserted:,}")
        log.info(f"Total rows in DB now: {final_count:,}")
        conn.close()

def load_env_key() -> str | None:
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GTFS_RT_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("GTFS_RT_API_KEY")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dublin Bus GTFS-RT collector")
    parser.add_argument("--api-key", default=None, help="NTA API key (or set GTFS_RT_API_KEY in .env)")
    parser.add_argument("--duration", type=int, default=180, help="Collection duration in minutes (default: 180)")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default: 60)")
    parser.add_argument("--label", default="", help="Label for this window, e.g. morning_peak")
    args = parser.parse_args()

    api_key = args.api_key or load_env_key()
    if not api_key:
        sys.exit(
            "ERROR: No API key found. Pass --api-key or set GTFS_RT_API_KEY in .env\n"
            "Register at https://developer.nationaltransport.ie/"
        )

    run(api_key, args.duration, args.interval, args.label)
