def cancel(s, key):
    if key not in s['holds']: return
    s['holds'].pop(next(iter(s['holds'])))
