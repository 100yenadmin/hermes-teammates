from tokenizing import tokens
def add(index,key,text):
    for token in tokens(text): index[token]={key}
def posting(index,token):
    return index.get(token,set())
