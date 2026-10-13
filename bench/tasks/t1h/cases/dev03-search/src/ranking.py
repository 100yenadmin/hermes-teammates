def top(rows,limit):
    return sorted(rows,key=lambda r:(r['score'],r['id']))[:limit+1]
