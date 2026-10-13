def unique(rows):
    seen=set(); result=[]
    for row in rows:
        key=row['id']
        if key not in seen: result.append(row)
        seen.add(key)
    return result
