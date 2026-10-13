def merge(base,overrides):
    return {**base,**{k:v for k,v in overrides.items() if v is not None}}
