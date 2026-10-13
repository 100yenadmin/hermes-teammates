# Expiring memo

Pure Python service; put src on the import path. Review supported behavior violations without editing.

TTL milliseconds becomes expiry seconds. now==expiry is stale. memo.get preserves false/zero; missing is None. Identity is tenant,key. service.fetch calls supplier once on miss. Negative TTL rejected; snapshot copies; clearing absent is no-op.
