def free(capacity,used):
    return [n for n in range(1,capacity) if n not in used]
def listed(used):
    return sorted(used)
