"""Read-only SQLite lineage/ledger extraction. Missing evidence stays null, never zero."""
import json
import sqlite3
from pathlib import Path

BUCKETS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')
TERMINAL = {'succeeded', 'failed', 'interrupted', 'cancelled', 'unknown'}


def observed(value):
    return {'value': value, 'label': 'OBSERVED'}


def read_table(path, table):
    if not Path(path).exists():
        return []
    if table not in {'sessions', 'messages', 'runs'}:
        raise ValueError('unsupported table')
    with sqlite3.connect(f'{Path(path).resolve().as_uri()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
            return []
        return [{key: ({'binary_bytes': len(value)} if isinstance(value, bytes) else value)
                 for key, value in dict(row).items()} for row in conn.execute(f'SELECT * FROM {table}')]


def sum_field(rows, field):
    if not rows or any(field not in row or row[field] is None for row in rows):
        return None
    return sum(row[field] for row in rows)


def extract(state, ledger, root_id):
    sessions = read_table(state, 'sessions')
    by_id = {row['id']: row for row in sessions}
    parent = [row for row in sessions if row['id'] == root_id]
    # Same-conversation continuations inherit source; delegates carry an edge marker.
    parent_ids = {root_id} if parent else set()
    while True:
        fresh = []
        for row in sessions:
            owner = row.get('parent_session_id')
            if owner not in parent_ids or row['id'] in parent_ids:
                continue
            metadata = json.loads(row.get('model_config') or '{}')
            if (by_id[owner].get('end_reason') == 'compression'
                    and row.get('source') == by_id[owner].get('source')
                    and not any(metadata.get(k) == owner for k in ('_delegate_from', '_branched_from'))):
                fresh.append(row)
        if not fresh:
            break
        parent.extend(fresh)
        parent_ids.update(row['id'] for row in fresh)
    ids = {root_id} if root_id else set()
    descendants = []
    while True:
        fresh = [row for row in sessions if row.get('parent_session_id') in ids and row['id'] not in ids]
        if not fresh:
            break
        descendants.extend(fresh)
        ids.update(row['id'] for row in fresh)
    children = [row for row in descendants if row['id'] not in parent_ids]
    parent_metrics = {field: sum_field(parent, field) for field in BUCKETS}
    child_metrics = {field: (sum_field(children, field) if children else (0 if parent else None)) for field in BUCKETS}
    def total(buckets):
        # cache_read/write are separate buckets; reasoning is a subset of output, not additive.
        fields = BUCKETS[:4]
        return sum(buckets[f] for f in fields) if all(buckets[f] is not None for f in fields) else None
    pt, ct = total(parent_metrics), total(child_metrics)
    pa = sum_field(parent, 'api_call_count')
    ca = sum_field(children, 'api_call_count') if children else (0 if parent else None)
    events = [(row['started_at'], 1) for row in children if row.get('started_at') is not None]
    events += [(row['ended_at'], -1) for row in children if row.get('ended_at') is not None]
    peak, live = 0, 0
    for _, delta in sorted(events):
        live += delta
        peak = max(peak, live)
    runs = [row for row in read_table(ledger, 'runs') if row.get('owner_session_id') in ids]
    metrics = {'parent_tokens': observed(pt), 'child_tokens': observed(ct),
               'total_tokens': observed(pt + ct if pt is not None and ct is not None else None),
               'parent_api_calls': observed(pa), 'child_api_calls': observed(ca),
               'api_calls': observed(pa + ca if pa is not None and ca is not None else None),
               'children_n': observed(len(children) if parent else None),
               'peak_concurrency': observed(peak if parent else None),
               'ledger_runs': observed(len(runs)),
               'ledger_terminal_coverage': observed(sum(row['status'] in TERMINAL for row in runs) / len(runs) if runs else None)}
    metrics.update({f'parent_{k}': observed(v) for k, v in parent_metrics.items()})
    metrics.update({f'child_{k}': observed(v) for k, v in child_metrics.items()})
    return {'metrics': metrics, 'sessions': parent + children, 'ledger': runs,
            'messages': [row for row in read_table(state, 'messages') if row['session_id'] in ids]}


def probe_metrics(path, root_id):
    available = Path(path).exists()
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()] if available else []
    parent = [row for row in rows if row.get('session_id') == root_id]
    schemas = [row['tool_schema_bytes'] for row in parent if 'tool_schema_bytes' in row]
    peaks = [row['prompt_tokens'] for row in parent if row.get('prompt_tokens') is not None]
    return {'tool_schema_bytes': observed(max(schemas) if schemas else None),
            'parent_peak_prompt_tokens': observed(max(peaks) if peaks else None),
            'request_attempts': observed(sum(row['hook'] == 'pre_api_request' for row in rows) if available else None),
            'probe_child_calls': observed(sum(row['hook'] == 'post_api_request' and row.get('session_id') != root_id for row in rows) if available else None)}
