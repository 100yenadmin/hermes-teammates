def billable(rows):
    return [r for r in rows if not r['approved']]
def label(value):
    return value
