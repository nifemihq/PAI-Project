import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from database import get_connection

conn = get_connection()

live_stops = [
    r[0]
    for r in conn.execute(
        "SELECT DISTINCT stop_id FROM delay_observations "
        "WHERE stop_id IS NOT NULL LIMIT 20"
    ).fetchall()
]

static_stops = [
    r[0] for r in conn.execute("SELECT stop_id FROM stops LIMIT 20").fetchall()
]

total_live = conn.execute(
    "SELECT COUNT(DISTINCT stop_id) FROM delay_observations "
    "WHERE stop_id IS NOT NULL"
).fetchone()[0]
matched = conn.execute(
    "SELECT COUNT(DISTINCT o.stop_id) FROM delay_observations o "
    "JOIN stops s ON o.stop_id = s.stop_id"
).fetchone()[0]

print(f"\nSample live feed stop IDs:  {live_stops[:8]}")
print(f"Sample static stop IDs:     {static_stops[:8]}")
print(f"\nDistinct live stop IDs:     {total_live:,}")
print(f"Matched to static stops:    {matched:,}  ({100*matched/total_live:.1f}%)")
print(
    f"Unmatched:                  {total_live-matched:,}  ({100*(total_live-matched)/total_live:.1f}%)"
)

unmatched = conn.execute(
    "SELECT DISTINCT o.stop_id FROM delay_observations o "
    "LEFT JOIN stops s ON o.stop_id = s.stop_id "
    "WHERE s.stop_id IS NULL AND o.stop_id IS NOT NULL LIMIT 10"
).fetchall()
print(f"\nSample unmatched live stop IDs: {[r[0] for r in unmatched]}")

conn.close()
