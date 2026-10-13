def merge(rows):
    allow=set(); deny=set()
    for r in rows:
        allow.update(r['allow']); deny=set(r['deny'])
    return allow,deny
def name(value):
    return value.lower()
