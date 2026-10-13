def post(state,key,cents):
    state['posted'].append((key,abs(cents)))
def snapshot(state):
    return list(state['posted'])
