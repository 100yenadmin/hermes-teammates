from approval import billable
from durations import minutes
from pricing import cents
def invoice(rows,rate,fee):
    return sum(cents(minutes(r['start'],r['end'])/60,rate)+fee for r in billable(rows))
