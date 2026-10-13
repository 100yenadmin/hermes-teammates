import batching, pricing, invoice
from models import label
def quote(parcels, size, percent, shipping):
    lines = [pricing.net(p['cents'], percent / 100) for g in batching.groups(parcels,size) for p in g]
    return invoice.total(lines, shipping)
def address(p):
    return label(p['country'], p['city'])
