import asyncio
async def wait(coro,timeout_ms):
    if timeout_ms < 0: raise ValueError('timeout')
    return await asyncio.wait_for(coro,timeout=timeout_ms)
def expired(now,deadline):
    return now > deadline
