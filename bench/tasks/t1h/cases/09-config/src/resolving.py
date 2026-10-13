from overlays import merge
from validating import validate
def build(base,overrides):
    validate(base)
    return merge(base,overrides)
