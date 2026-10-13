# Parcel pricing

Pure Python service; use src on the import path. Inputs obey the domains below unless a rejection rule is stated. Public entry points compose the named helpers. Review concrete observable violations of this contract. Do not edit files.

dispatch.quote prices all parcels, including partial final groups. pricing.net takes integer cents and a percentage in [0,100]; the discount is floor(cents*percent/100). invoice.total charges shipping once even for an empty order. billing inputs are nonnegative; a negative discount is rejected. labels use city, country order. batching.groups rejects nonpositive sizes. Inclusive IDs include both ends; whole_dollars deliberately floors; code normalization strips spaces and uppercases; an empty batch list is valid.
