def event(source, id, minute, offset_minutes, kind, payload=''):
    return dict(source=source,id=id,minute=minute,offset_minutes=offset_minutes,kind=kind,payload=payload)
