from release import cancel
def fulfil(s, key):
    qty = s['holds'][key]
    s['on_hand'] += qty
    cancel(s,key)
def total(lines):
    return sum(lines)
