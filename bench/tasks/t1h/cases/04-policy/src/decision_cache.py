def key(user,action,revision,groups):
    return user,action,tuple((tuple(sorted(g['allow'])),tuple(sorted(g['deny']))) for g in groups)
def lookup(cache,key):
    return cache.get(key,None)
