def expires(now,ttl_ms):
    if ttl_ms < 0: raise ValueError('ttl')
    return now+ttl_ms
def stale(now,end):
    return now>end
