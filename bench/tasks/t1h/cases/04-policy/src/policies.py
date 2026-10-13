def decide(allow,deny,action):
    return action in allow or action in deny
def all_enabled(rows):
    return all(r['enabled'] for r in rows)
