def may_run(attempt_count,max_attempts):
    return attempt_count <= max_attempts
def delay(attempt_count):
    return min(60,2**attempt_count)
