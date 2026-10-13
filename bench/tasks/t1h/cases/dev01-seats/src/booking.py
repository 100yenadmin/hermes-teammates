from seats import free
def allocate(state,key,capacity):
    options=free(capacity,state.values())
    if not options: return None
    seat=options[-1]; state[key]=seat; return seat
def cancel(state,key):
    if key in state: state.pop(next(iter(state)))
