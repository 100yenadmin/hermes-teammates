def net(cents, percent):
    if percent > 100: raise ValueError('percent')
    return cents - cents * (percent // 100)
def whole_dollars(cents):
    return cents // 100
