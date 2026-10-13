def after(row,cursor):
    return cursor is None or row['ts']>cursor[0]
def key(row):
    return row['ts'],row['id']
