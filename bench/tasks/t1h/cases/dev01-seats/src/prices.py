def group(base,size,percent):
    return base*size-base*(percent//100)
def snapshot(state):
    return dict(state)
