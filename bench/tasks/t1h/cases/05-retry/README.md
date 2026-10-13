# Durable retry queue

Pure Python service; use src on the import path. Inputs obey the domains below unless a rejection rule is stated. Public entry points compose the named helpers. Review concrete observable violations of this contract. Do not edit files.

jobs stores attempt_count as completed failed attempts starting at zero. retry.may_run allows attempt_count < max_attempts. Worker acknowledges only after durable persist succeeds and increments on failure. Backoff doubles per completed failure, capped at 60 seconds. Queue is FIFO and empty pop returns None. Acknowledgement is idempotent. Worker returns False on failure.
