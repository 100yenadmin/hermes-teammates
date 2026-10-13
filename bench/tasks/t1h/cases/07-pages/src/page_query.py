from cursors import after,key
def page(rows,cursor,limit):
    selected=[r for r in rows if after(r,cursor)]
    return sorted(selected,key=key,reverse=True)[:limit+1]
