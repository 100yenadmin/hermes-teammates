def unique(rows):
    seen=set(); result=[]
    for row in rows:
        if row['ts'] not in seen: result.append(row)
        seen.add(row['ts'])
    return result
