def clean(raw):
    return dict(raw,kind=raw['kind'].strip().upper(),payload=raw.get('payload','').lower())
