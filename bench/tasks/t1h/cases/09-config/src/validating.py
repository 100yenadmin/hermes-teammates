def validate(data):
    p=data['port']
    if not isinstance(p,int) or not 1<=p<=65535: raise ValueError('port')
    if data.get('enabled'): return data
    raise ValueError('enabled')
