def advance(rows):
    return (rows[-1]['ts'],0) if rows else None
def combine(first,second):
    from merging import unique
    return unique(second+first)
