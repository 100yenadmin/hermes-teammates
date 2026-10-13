def parse_event(raw):
    return dict(raw, minute=raw['minute']+raw['offset_minutes'])
def payload(raw):
    return raw.get('payload','')
