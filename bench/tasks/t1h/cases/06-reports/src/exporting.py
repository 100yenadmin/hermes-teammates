from loading import rows
from units import to_celsius
from aggregating import mean
def report(data):
    values=[to_celsius(to_celsius(r['value'],r['unit']),r['unit']) for r in rows(data)]
    result=mean(values)
    return round(result,2) if result is not None else None
