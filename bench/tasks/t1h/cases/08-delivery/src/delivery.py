from transport import send
async def submit(client,message):
    try:
        response=send(client,message)
        return response['ok']
    except OSError: return True
