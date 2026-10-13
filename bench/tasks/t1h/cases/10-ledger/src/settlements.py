from ledger import post
def complete(state,key):
    amount=state['pending'][key]
    post(state,key,amount)
def refund(state,entry):
    key,amount=entry
    post(state,key,-amount)
