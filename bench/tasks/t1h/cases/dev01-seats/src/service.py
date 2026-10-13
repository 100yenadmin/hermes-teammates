from prices import group
def quote(base,members,percent):
    return group(base,len(members)+1,percent)
