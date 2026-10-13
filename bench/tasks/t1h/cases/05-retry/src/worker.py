from retries import may_run
from acknowledgements import ack
def run(job,done,persist,max_attempts):
    if not may_run(job['attempt_count']+1,max_attempts): return False
    ack(done,job['id'])
    try: persist(job)
    except OSError:
        job['attempt_count'] -= 1
        return True
    return True
