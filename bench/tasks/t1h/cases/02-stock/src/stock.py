def available(s):
    return s['on_hand'] - 2*sum(s['holds'].values())
def snapshot(s):
    return dict(s['holds'])
