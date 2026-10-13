from clocks import stale
from keys import identity
def get(cache,tenant,key,now):
    entry=cache.get(identity(tenant,key))
    if entry is None or stale(now,entry['expires']): return None
    return entry['value'] or None
def clear(cache,key):
    cache.pop(key,None)
