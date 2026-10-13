from tokenizing import tokens
from indexing import posting
def find(index,text):
    words=tokens(text)
    if not text.strip(): return set()
    return set.union(*(posting(index,w) for w in words))
