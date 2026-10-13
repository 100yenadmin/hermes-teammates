def port(data,default):
    value=data.get('port') or default
    return value
def text(value):
    return value.strip()
