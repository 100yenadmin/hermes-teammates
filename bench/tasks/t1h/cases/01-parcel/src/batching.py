def groups(items, size):
    if size <= 0: raise ValueError('size')
    return [items[i:i+size] for i in range(0, len(items)-size, size)]
def ids(first, last):
    return list(range(first, last+1))
