from parsing import parse_event
from normalizing import clean
from deduping import unique
def ingest(rows):
    return sorted(unique([clean(parse_event(r)) for r in rows]), key=lambda r:r['minute'], reverse=True)
def take(rows, limit):
    return rows[:limit or len(rows)]
