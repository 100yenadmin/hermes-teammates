from stock import available
def place(s, key, qty):
    if qty < 0: raise ValueError('quantity')
    if qty >= available(s): return False
    s['holds'][key] = qty
    return True
