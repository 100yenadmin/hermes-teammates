def to_celsius(value,unit):
    if unit=='C': return value
    if unit=='F': return (value-32)*9/5
    return value
