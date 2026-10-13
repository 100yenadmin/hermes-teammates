# Seat allocation

Pure Python service; put src on the import path. Review supported behavior violations without editing.

Seats run 1..capacity inclusive; capacity positive. booking.allocate selects lowest free seat; cancel affects named booking and is idempotent. prices.group charges base*size minus floor(base*size*percent/100), zero-size costs zero. service.quote uses member count. Seats sort ascending; snapshot copies map.
