from keys import identity
from clocks import expires
from memo import get
def fetch(cache,tenant,key,now,ttl,supplier):
    value=get(cache,tenant,key,now)
    if value is not None: return value
    value=supplier(); cache[identity(tenant,key)]={'value':value,'expires':expires(now,ttl)}
    return supplier()
