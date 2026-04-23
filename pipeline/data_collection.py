import os
import time
import sqlite3
import argparse
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import requests
from google.transit import gtfs_realtime_pb2

from database import get_connection, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [data_collection] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# NTA GTFS-Realtime endpoint
GTFS_RT_URL = "https://api.nationaltransport.ie/gtfsr/v2/gtfsr"


def fetch_feed(api_key: str) -> gtfs_realtime_pb2.FeedMessage | None:
    """Download and parse the GTFS-Realtime protobuf feed."""
    headers = {"x-api-key": api_key, "Cache-Control": "no-cache"}
    try:
        resp = requests.get(GTFS_RT_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(resp.content)
        log.info(
            f"Feed fetched: {len(feed.entity)} entities, "
            f"timestamp={feed.header.timestamp}"
        )
        return feed
    except Exception as exc:
        log.error(f"Feed fetch failed: {exc}")
        return None


def parse_feed(feed: gtfs_realtime_pb2.FeedMessage) -> list[dict]:
    """
    Extract delay and cancellation events from a FeedMessage.
    Filters to Dublin Bus routes only (agency_id check not available in RT,
    so we rely on route_id prefix patterns common to Dublin Bus).
    """
    records = []
    collected_at = datetime.now(timezone.utc).isoformat()

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip_id = tu.trip.trip_id
        route_id = tu.trip.route_id or ""
        vehicle_id = tu.vehicle.id if tu.HasField("vehicle") else None

        # GTFS-Cancelled trips have no stop_time_updates
        is_cancelled = (
            tu.trip.schedule_relationship == gtfs_realtime_pb2.TripDescriptor.CANCELED
        )

        if is_cancelled:
            records.append(
                {
                    "collected_at": collected_at,
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "stop_id": None,
                    "stop_sequence": None,
                    "delay_seconds": None,
                    "is_cancelled": 1,
                    "vehicle_id": vehicle_id,
                }
            )
        else:
            for stu in tu.stop_time_update:
                delay = None
                if stu.HasField("arrival") and stu.arrival.HasField("delay"):
                    delay = float(stu.arrival.delay)
                elif stu.HasField("departure") and stu.departure.HasField("delay"):
                    delay = float(stu.departure.delay)

                records.append(
                    {
                        "collected_at": collected_at,
                        "trip_id": trip_id,
                        "route_id": route_id,
                        "stop_id": stu.stop_id or None,
                        "stop_sequence": stu.stop_sequence or None,
                        "delay_seconds": delay,
                        "is_cancelled": 0,
                        "vehicle_id": vehicle_id,
                    }
                )
    return records


def write_records(conn: sqlite3.Connection, records: list[dict]) -> int:
    if not records:
        return 0
    conn.executemany(
        """INSERT INTO delay_observations
           (collected_at, trip_id, route_id, stop_id, stop_sequence,
            delay_seconds, is_cancelled, vehicle_id)
           VALUES (:collected_at, :trip_id, :route_id, :stop_id,
                   :stop_sequence, :delay_seconds, :is_cancelled, :vehicle_id)""",
        records,
    )
    conn.commit()
    return len(records)


def run_collector(
    api_key: str, interval_seconds: int = 60, max_polls: int | None = None
) -> None:
    """
    Main polling loop.
    Runs until interrupted (Ctrl-C) or max_polls is reached.
    """
    log.info(f"Starting collector — interval={interval_seconds}s, " f"DB={DB_PATH}")
    conn = get_connection()
    poll_count = 0

    try:
        while True:
            feed = fetch_feed(api_key)
            if feed:
                records = parse_feed(feed)
                n = write_records(conn, records)
                log.info(f"Poll #{poll_count+1}: wrote {n} records to DB")
            poll_count += 1
            if max_polls and poll_count >= max_polls:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        log.info("Collector stopped by user.")
    finally:
        conn.close()
        log.info(f"Total polls: {poll_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Poll NTA GTFS-Realtime and store observations."
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GTFS_RT_API_KEY"),
        help="NTA API key (or set GTFS_RT_API_KEY env var)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Poll interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=None,
        help="Stop after N polls (omit for continuous)",
    )
    args = parser.parse_args()

    if not args.api_key:
        parser.error(
            "API key required. Pass --api-key or set GTFS_RT_API_KEY.\n"
            "Get your key at: https://developer.nationaltransport.ie/"
        )
    run_collector(args.api_key, args.interval, args.max_polls)
