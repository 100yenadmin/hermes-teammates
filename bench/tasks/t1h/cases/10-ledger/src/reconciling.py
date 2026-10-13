def balance(state):
    return sum(v for k,v in state['posted'])+sum(state['pending'].values())
def key(value):
    return value.lower()
