from groups import merge
from policies import decide
from decision_cache import key
def check(cache,user,action,revision,rows):
    k=key(user,action,revision,rows)
    if k in cache: return cache[k]
    allow,deny=merge(rows[:1])
    cache[k]=decide(allow,deny,action)
    return cache[k]
