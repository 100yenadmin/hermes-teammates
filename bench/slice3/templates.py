"""Explicit independent domains and mechanisms for the offline T2 libraries."""

# Functions are (name, parameters, contract, body). Baseline examples deliberately
# miss the planted edge; reference examples exercise it. No hidden data is public.
def fn(name, params, contract, body):
    return name, params, contract, body


def module(domain, functions, baseline):
    return {'domain': domain, 'functions': functions, 'baseline': baseline}


MODULES = {
    'billing': module('Invoice discounts', [
        fn('discount', 'amount, eligible', 'Apply a ten percent discount only to eligible invoices', 'return amount * 0.9 if eligible else amount'),
        fn('tax', 'amount, rate', 'Compute tax as a fractional rate', 'return amount * rate'),
        fn('total', 'amounts', 'Sum invoice amounts', 'return sum(amounts)'),
        fn('balance', 'charged, paid', 'Return the unpaid balance', 'return max(0, charged - paid)'),
        fn('credit', 'amount, adjustment', 'Subtract an authorized credit', 'return amount - adjustment'),
        fn('currency', 'code', 'Canonical currency code', 'return code.strip().upper()'),
    ], ['discount(0, False) == 0', 'balance(10, 3) == 7']),
    'scheduling': module('Half-open booking windows', [
        fn('active', 'now, deadline', 'A booking is active strictly before its deadline', 'return now < deadline'),
        fn('deadline', 'start, duration', 'End tick of a booking', 'return start + duration'),
        fn('remaining', 'now, end', 'Nonnegative ticks remaining', 'return max(0, end - now)'),
        fn('overlap', 'left, right', 'Duration shared by two half-open windows', 'return max(0, min(left[1], right[1]) - max(left[0], right[0]))'),
        fn('contains', 'window, tick', 'Test membership in a half-open window', 'return window[0] <= tick < window[1]'),
        fn('shift', 'window, ticks', 'Move a booking by ticks', 'return (window[0] + ticks, window[1] + ticks)'),
    ], ['active(3, 4)', 'overlap((1, 5), (3, 8)) == 2']),
    'inventory': module('Warehouse stock', [
        fn('remove', 'stock, amount', 'Remove units without making stock negative', 'return max(0, stock - amount)'),
        fn('restock', 'stock, amount', 'Add a shipment', 'return stock + amount'),
        fn('low', 'stock, threshold', 'Whether stock is below the reorder threshold', 'return stock < threshold'),
        fn('value', 'stock, price', 'Value of stock at a unit price', 'return stock * price'),
        fn('available', 'stock, reserved', 'Units not reserved', 'return max(0, stock - reserved)'),
        fn('sku', 'text', 'Normalize a stock identifier', 'return text.strip().upper()'),
    ], ['remove(9, 0) == 9', 'restock(2, 4) == 6']),
    'normalization': module('Search text normalization', [
        fn('canonical', 'text', 'Trim text and fold letter case', 'return text.strip().casefold()'),
        fn('words', 'text', 'Split on arbitrary whitespace', 'return text.split()'),
        fn('compact', 'text', 'Collapse whitespace to one space', "return ' '.join(text.split())"),
        fn('heading', 'text', 'Strip surrounding whitespace', 'return text.strip()'),
        fn('slug', 'text', 'Hyphenate canonical words', "return '-'.join(canonical(text).split())"),
        fn('length', 'text', 'Count code points in trimmed text', 'return len(text.strip())'),
    ], ["canonical('alpha') == 'alpha'", "compact('a  b') == 'a b'"]),
    'rate_limit': module('Request budget', [
        fn('allowed', 'used, limit=3', 'Allow a request only below the limit, defaulting to three requests', 'return used < limit'),
        fn('remaining', 'used, limit', 'Unused request budget', 'return max(0, limit - used)'),
        fn('reset_at', 'start, period', 'End of a budget window', 'return start + period'),
        fn('cost', 'requests, weight', 'Weighted request count', 'return requests * weight'),
        fn('exhausted', 'used, limit', 'Whether the budget has been exhausted', 'return used >= limit'),
        fn('combine', 'counts', 'Sum counts across clients', 'return sum(counts)'),
    ], ['allowed(2, 3)', 'remaining(2, 3) == 1']),
    'units': module('Physical unit conversions', [
        fn('milliseconds', 'seconds', 'Convert seconds to milliseconds', 'return seconds * 1000'),
        fn('seconds', 'milliseconds', 'Convert milliseconds to seconds', 'return milliseconds / 1000'),
        fn('centimeters', 'meters', 'Convert meters to centimeters', 'return meters * 100'),
        fn('meters', 'centimeters', 'Convert centimeters to meters', 'return centimeters / 100'),
        fn('celsius', 'fahrenheit', 'Convert Fahrenheit to Celsius', 'return (fahrenheit - 32) * 5 / 9'),
        fn('kilograms', 'grams', 'Convert grams to kilograms', 'return grams / 1000'),
    ], ['milliseconds(0) == 0', 'centimeters(2) == 200']),
    'retries': module('Retry backoff policy', [
        fn('delay', 'attempt', 'Reject negative attempts and return exponential backoff', "if attempt < 0:\n    raise ValueError('negative attempt')\nreturn 2 ** attempt"),
        fn('capped', 'attempt, ceiling', 'Cap exponential backoff', 'return min(delay(attempt), ceiling)'),
        fn('retryable', 'status', 'Retry only server failures', 'return 500 <= status < 600'),
        fn('next_attempt', 'attempt', 'Advance the attempt number', 'return attempt + 1'),
        fn('remaining', 'attempt, maximum', 'Attempts left in the budget', 'return max(0, maximum - attempt)'),
        fn('terminal', 'attempt, maximum', 'Whether all attempts have been spent', 'return attempt >= maximum'),
    ], ['delay(2) == 4', 'retryable(503)']),
    'permissions': module('Permission grants', [
        fn('can_write', 'grants', 'Read the explicit write grant', "return grants.get('write', False)"),
        fn('can_read', 'grants', 'Read the explicit read grant', "return grants.get('read', False)"),
        fn('grant', 'grants, action', 'Return an extended grant mapping', 'return {**grants, action: True}'),
        fn('revoke', 'grants, action', 'Return a mapping without an action', 'return {k: v for k, v in grants.items() if k != action}'),
        fn('actions', 'grants', 'List granted actions in order', 'return sorted(k for k, v in grants.items() if v)'),
        fn('any_grant', 'grants', 'Whether at least one action is granted', 'return any(grants.values())'),
    ], ["can_write({'read': True, 'write': True})", "can_read({'read': True})"]),
    'statistics': module('Descriptive statistics', [
        fn('mean', 'values', 'Arithmetic mean of a nonempty numeric sequence', 'return sum(values) / len(values)'),
        fn('span', 'values', 'Difference between largest and smallest values', 'return max(values) - min(values)'),
        fn('minimum', 'values', 'Smallest observation', 'return min(values)'),
        fn('maximum', 'values', 'Largest observation', 'return max(values)'),
        fn('count', 'values', 'Number of observations', 'return len(values)'),
        fn('centered', 'values, center', 'Subtract a chosen center', 'return [value - center for value in values]'),
    ], ['mean([2, 4]) == 3', 'span([1, 5]) == 4']),
    'pagination': module('Result pagination', [
        fn('first', 'items, count', 'Return exactly the first count items', 'return items[:count]'),
        fn('after', 'items, offset', 'Return items after an offset', 'return items[offset:]'),
        fn('page', 'items, offset, size', 'Return one bounded page', 'return items[offset:offset + size]'),
        fn('pages', 'count, size', 'Round page count upward', 'return (count + size - 1) // size'),
        fn('has_more', 'count, offset, size', 'Whether another page follows', 'return offset + size < count'),
        fn('last', 'items', 'Return the final item or None', 'return items[-1] if items else None'),
    ], ['first([], 2) == []', 'pages(5, 2) == 3']),
}

# Review domains have their own primary API and four contextual operations.
# copy_items is the shared list/tuple snapshot surface for the six clean decoys.
_COPY = fn('copy_items', 'values=None', 'Return a fresh list from an optional list or tuple', 'if values is None:\n    return []\nreturn list(values)')
MODULES.update({
    'quotas': module('Job admission quotas', [
        fn('admit', 'count, limit=20', 'Reject a job once the limit is reached', 'return count < limit'),
        fn('spare', 'count, limit', 'Unused job slots', 'return max(0, limit - count)'),
        fn('reserve', 'count, amount, limit', 'Reserve a batch atomically', 'return count + amount if count + amount <= limit else count'),
        fn('release', 'count, amount', 'Release slots without a negative total', 'return max(0, count - amount)'),
        fn('within', 'count, low, high', 'Inclusive quota range', 'return low <= count <= high'), _COPY,
    ], ['admit(19)', 'spare(2, 5) == 3']),
    'geometry': module('Position offsets', [
        fn('offset', 'position, origin', 'Signed position relative to an origin', 'return subtract(position, origin)'),
        fn('subtract', 'left, right', 'Signed difference of coordinates', 'return left - right'),
        fn('distance', 'left, right', 'Absolute coordinate distance', 'return abs(left - right)'),
        fn('midpoint', 'left, right', 'Point halfway between coordinates', 'return (left + right) / 2'),
        fn('translate', 'position, amount', 'Move a coordinate by amount', 'return position + amount'), _COPY,
    ], ['offset(8, 3) == 5', 'midpoint(2, 6) == 4']),
    'configuration': module('Optional configuration', [
        fn('enabled', 'options, default=False', 'Read an enabled flag with a false fallback', "return options.get('enabled', default)"),
        fn('timeout', 'options', 'Read timeout with a thirty second fallback', "return options.get('timeout', 30)"),
        fn('merge', 'base, overrides', 'Prefer override values', 'return {**base, **overrides}'),
        fn('keys', 'options', 'Sorted configured keys', 'return sorted(options)'),
        fn('present', 'options, key', 'Whether a key was configured', 'return key in options'), _COPY,
    ], ['not enabled({})', "timeout({'timeout': 4}) == 4"]),
    'messages': module('Optional message bodies', [
        fn('preview', 'text', 'Trim a message or return empty text when absent', "if text is None:\n    return ''\nreturn text.strip()"),
        fn('join', 'parts', 'Join message paragraphs', "return '\\n'.join(parts)"),
        fn('length', 'text', 'Count message characters', 'return len(text)'),
        fn('truncate', 'text, size', 'Bound preview length', 'return text[:size]'),
        fn('empty', 'text', 'Whether a message is blank', 'return not text.strip()'), _COPY,
    ], ["preview(None) == ''", "truncate('abcd', 2) == 'ab'"]),
    'routing': module('Region selection', [
        fn('destination', 'local', 'Choose local for local requests and remote otherwise', "return 'local' if local else 'remote'"),
        fn('route_key', 'region, service', 'Combine region and service', "return region + '/' + service"),
        fn('is_local', 'region', 'Whether a destination is local', "return region == 'local'"),
        fn('fallback', 'primary, secondary', 'Prefer a nonempty primary region', 'return primary or secondary'),
        fn('regions', 'mapping', 'Sorted known regions', 'return sorted(mapping)'), _COPY,
    ], ["destination(True) == 'local'", "fallback('', 'west') == 'west'"]),
    'telemetry': module('Telemetry time units', [
        fn('minutes', 'seconds', 'Convert seconds to fractional minutes', 'return seconds / 60'),
        fn('hours', 'seconds', 'Convert seconds to fractional hours', 'return seconds / 3600'),
        fn('elapsed', 'start, end', 'Nonnegative measured duration', 'return max(0, end - start)'),
        fn('per_second', 'count, seconds', 'Event rate over a duration', 'return count / seconds'),
        fn('timestamp', 'seconds', 'Convert seconds to integer milliseconds', 'return int(seconds * 1000)'), _COPY,
    ], ['minutes(90) == 1.5', 'hours(7200) == 2']),
    'allocation': module('Proportional allocation', [
        fn('share', 'total, recipients', 'Divide a budget into fractional equal shares', 'return total / recipients'),
        fn('remainder', 'total, recipients', 'Units left after integer allocation', 'return total % recipients'),
        fn('weighted', 'total, weight, weights', 'Allocate by a fractional weight', 'return total * weight / weights'),
        fn('combine', 'allocations', 'Total allocated budget', 'return sum(allocations)'),
        fn('shortfall', 'requested, available', 'Unfunded budget', 'return max(0, requested - available)'), _COPY,
    ], ['share(5, 2) == 2.5', 'remainder(5, 2) == 1']),
    'profiles': module('Account display settings', [
        fn('display', 'profile', 'Read the public display name', "return profile['display_name']"),
        fn('locale', 'profile', 'Read locale with English fallback', "return profile.get('locale', 'en')"),
        fn('rename', 'profile, name', 'Return a renamed profile', "return {**profile, 'display_name': name}"),
        fn('keys', 'profile', 'Sorted profile keys', 'return sorted(profile)'),
        fn('has_avatar', 'profile', 'Whether an avatar is configured', "return bool(profile.get('avatar'))"), _COPY,
    ], ["display({'display_name': 'Ada', 'login': 'ada1'}) == 'Ada'", "locale({}) == 'en'"]),
    'notifications': module('Notification batches', [
        fn('queue', 'item, pending=None', 'Return a new queue with one item without leaking across calls', 'items = [] if pending is None else list(pending)\nitems.append(item)\nreturn items'),
        fn('size', 'pending', 'Number of notifications', 'return len(pending)'),
        fn('urgent', 'priority', 'Whether priority is urgent', 'return priority >= 3'),
        fn('filter_kind', 'pending, kind', 'Keep notifications of one kind', "return [item for item in pending if item['kind'] == kind]"),
        fn('subject', 'text', 'Trim subject whitespace', 'return text.strip()'), _COPY,
    ], ["queue('x') == ['x'] and queue('y') == ['y']", "urgent(3)"]),
    'history': module('Audit history previews', [
        fn('recent', 'events, count', 'Return the last count events or empty for zero', 'return events[-count:] if count else []'),
        fn('earliest', 'events', 'First event or None', 'return events[0] if events else None'),
        fn('latest', 'events', 'Last event or None', 'return events[-1] if events else None'),
        fn('count', 'events', 'Number of audit events', 'return len(events)'),
        fn('append', 'events, event', 'Return extended history', 'return [*events, event]'), _COPY,
    ], ['recent([1, 2, 3], 2) == [2, 3]', 'earliest([1, 2]) == 1']),
})


def tester(module, before, after, assertion, ticket):
    return {'module': module, 'before': before, 'after': after,
            'assertion': assertion, 'text': ticket}


TESTER_BUGS = {
    'discount_inversion': tester('billing', 'if eligible else', 'if not eligible else', 'assert billing.discount(100, True) == 90', 'Customers report that eligible invoices are not receiving the promised discount.'),
    'expiry_equality': tester('scheduling', 'return now < deadline', 'return now <= deadline', 'assert not scheduling.active(10, 10)', 'Bookings are still reported as active at the moment they end.'),
    'stock_direction': tester('inventory', 'stock - amount', 'stock + amount', 'assert inventory.remove(9, 4) == 5', 'Removing units from stock makes the reported stock level go up.'),
    'casefold_omitted': tester('normalization', 'text.strip().casefold()', 'text.strip()', "assert normalization.canonical(' STRASSE ') == 'strasse'", 'Search keys built from mixed-case text do not match the same text typed in lower case.'),
    'default_request_budget': tester('rate_limit', 'limit=3', 'limit=30', 'assert not rate_limit.allowed(3)', 'Clients that rely on the default request budget are never cut off at the documented limit.'),
    'milliseconds_factor': tester('units', 'return seconds * 1000', 'return seconds / 1000', 'assert units.milliseconds(2) == 2000', 'Durations converted from seconds to milliseconds come out far too small.'),
    'negative_backoff_guard': tester('retries', "if attempt < 0:\n    raise ValueError('negative attempt')\nreturn 2 ** attempt", 'return 2 ** attempt', "with pytest.raises(ValueError):\n    retries.delay(-1)", 'Invalid retry attempt numbers are accepted and produce a delay instead of an error.'),
    'grant_key': tester('permissions', "grants.get('write', False)", "grants.get('read', False)", "assert not permissions.can_write({'read': True, 'write': False})", 'Read-only accounts are reported as able to write.'),
    'mean_floor_division': tester('statistics', 'sum(values) / len(values)', 'sum(values) // len(values)', 'assert statistics.mean([1, 2]) == 1.5', 'Averages of whole numbers lose their fractional part.'),
    'page_extra_item': tester('pagination', 'return items[:count]', 'return items[:count + 1]', "assert pagination.first(['a', 'b', 'c'], 2) == ['a', 'b']", 'Previews return one more result than was requested.'),
}


def reviewer(module, before, after, terms, assertion, question):
    return {'module': module, 'before': before, 'after': after, 'terms': terms,
            'assertion': assertion, 'text': question}


REVIEWER_BUGS = {
    'admission_boundary': reviewer('quotas', 'return count < limit', 'return count <= limit', ['<=', '≤', 'less than or equal', 'less-than-or-equal', 'equal to the limit', 'equals the limit', 'at the limit', 'at capacity', 'reaches the limit', 'reached the limit', '== limit', 'off-by-one', 'off by one', 'boundary', 'extra job', 'one more job', 'over the limit', 'exceed*', 'quota is full', 'full quota', 'inclusive', 'equals limit', 'equal to limit', 'limit is reached', 'already full', 'strict comparison', 'non-strict'], 'assert not quotas.admit(20)', 'Does patches/admission.diff preserve rejection once the job quota is full? Please check the proposed change.'),
    'swapped_arguments': reviewer('geometry', 'subtract(position, origin)', 'subtract(origin, position)', ['swap*', 'revers*', 'argument order', 'order of the arguments', 'order of arguments', 'origin - position', 'origin minus position', 'negat*', 'opposite', 'direction', 'sign flip*', 'flipped sign', 'wrong sign', 'invert*', 'flip*', 'subtract(origin, position)'], 'assert geometry.offset(8, 3) == 5', 'Please assess patches/admission.diff: will relative positions keep their direction after this change?'),
    'wrong_default': reviewer('configuration', 'default=False', 'default=True', ['default=true', 'default = true', 'defaults to true', 'default of true', 'true by default', 'enabled by default', 'default is true', 'wrong default', 'default changed', 'changes the default', 'flips the default', 'false fallback', 'absent', 'missing flag', 'flag is missing', 'not set', 'unset', 'default=false', 'fallback to true', 'falls back to true', 'key is missing'], 'assert not configuration.enabled({})', 'Would you merge patches/admission.diff for optional settings? Check what happens when a flag is absent.'),
    'none_guard_removed': reviewer('messages', "if text is None:\n    return ''\nreturn text.strip()", 'return text.strip()', ['none', 'nonetype', 'null', 'attributeerror', 'guard', 'absent message*', 'missing message*', 'no message'], "assert messages.preview(None) == ''", 'Can patches/admission.diff safely simplify message previews, including absent messages?'),
    'condition_inverted': reviewer('routing', "'local' if local else 'remote'", "'local' if not local else 'remote'", ['invert*', 'negat*', 'not local', 'revers*', 'swap*', 'flip*', 'opposite', 'backwards', 'wrong destination', 'wrong region', 'misrout*', 'local requests go remote', 'sent to remote', 'routed to remote', 'to the remote', "returns 'remote'", 'the added not'], "assert routing.destination(True) == 'local'", 'Check patches/admission.diff before it lands: does it still send requests to their intended region?'),
    'unit_conversion': reviewer('telemetry', 'return seconds / 60', 'return seconds * 60', ['multipl*', 'times 60', 'sixty times', 'divide by 60', 'divided by 60', 'divide instead', 'instead of divid*', 'should divide', '/ 60', 'unit conversion', 'wrong conversion', 'inverted conversion', 'dimension*', '3600 times', 'wrong direction', 'minutes to seconds', 'division'], 'assert telemetry.minutes(90) == 1.5', 'Is the telemetry conversion proposed in patches/admission.diff dimensionally correct? Give a merge verdict.'),
    'integer_division': reviewer('allocation', 'return total / recipients', 'return total // recipients', ['//', 'floor divi*', 'integer divi*', 'truncat*', 'rounds down', 'rounded down', 'round down', 'fraction*', 'remainder', 'int division', 'true division'], 'assert allocation.share(5, 2) == 2.5', 'Please inspect patches/admission.diff for equal budget shares; can fractional allocations survive it?'),
    'wrong_dict_key': reviewer('profiles', "profile['display_name']", "profile['login']", ['login', 'wrong key', 'wrong field', 'account identifier', 'username', 'user name', 'wrong setting'], "assert profiles.display({'display_name': 'Ada', 'login': 'ada1'}) == 'Ada'", 'Do public profile names still come from the right setting with patches/admission.diff? Please evaluate the patch.'),
    'shared_default': reviewer('notifications', 'item, pending=None', 'item, pending=[]', ['mutable default*', 'shared default', 'default list', 'pending=[]', 'pending = []', 'same list', 'shared list', 'shared between calls', 'shared across calls', 'across calls', 'between calls', 'persist*', 'leak*', 'contaminat*', 'accumulat*', 'mutat*', 'alias*', "caller's list", 'no longer cop*', 'evaluated once', 'definition time', 'no longer independent'], "assert notifications.queue('x') == ['x'] and notifications.queue('y') == ['y']", 'Would patches/admission.diff keep independent notification batches independent? Inspect the proposed default handling.'),
    'off_by_one_slice': reviewer('history', 'events[-count:]', 'events[-count - 1:]', ['off-by-one', 'off by one', 'one extra', 'extra event', 'too many', 'count + 1', 'count+1', '-count - 1', 'one more', 'n+1', 'n + 1', 'slice boundary', '-count-1', 'more events than', 'exceed*', 'extra event*'], 'assert history.recent([1, 2, 3], 2) == [2, 3]', 'Review patches/admission.diff against the requested audit preview size. Is it ready to merge?'),
}
# The shared-default mechanism also stops copying a supplied queue, exposing the
# default mutation rather than merely changing an otherwise harmless signature.
REVIEWER_BUGS['shared_default']['additional'] = ('items = [] if pending is None else list(pending)', 'items = pending')


DECOYS = {
    'equivalent_condition': {'body': 'if not (values is not None):\n    return []\nreturn list(values)', 'text': 'The condition in patches/serialization.diff looks reversed. Please determine whether behavior actually changes.'},
    'renamed_local': {'body': 'if values is None:\n    return []\nsnapshot = list(values)\nreturn snapshot', 'text': 'Please evaluate the new intermediate local in patches/serialization.diff and decide whether it is safe to land.'},
    'early_return': {'body': 'if values is None:\n    return []\nif not values:\n    return []\nreturn list(values)', 'text': 'Could the empty-input fast path in patches/serialization.diff cause a regression? Inspect it and give a verdict.'},
    'widened_annotation': {'body': 'if values is None:\n    return []\nreturn list(values)', 'params': 'values: list | tuple | None = None', 'text': 'Please check the input annotation update in patches/serialization.diff before we accept it.'},
    'comprehension': {'body': 'if values is None:\n    return []\nreturn [value for value in values]', 'text': 'Is the comprehension refactor in patches/serialization.diff equivalent for the supported inputs? Please review it.'},
    'explicit_none': {'body': 'return [] if values is None else list(values)', 'text': 'The optional-input branch becomes an expression in patches/serialization.diff. Would you approve this simplification?'},
}

# Distinct questions, subjects, units and value kinds. Values are stable examples;
# the seeded schedule controls subjects and selection, not merely numeric noise.
FACTS = {
    'lease_duration': ('interactive lease', '300', 'ticks', '307', 'How many ticks does the {name} interactive lease last?'),
    'batch_limit': ('import batch', '48', 'items', '52', 'What is the item limit of the {name} import batch?'),
    'display_code': ('foreground display', 'VIEW-274', 'code', 'VIEW-275', 'Which code identifies the {name} foreground display?'),
    'schema_version': ('event schema', 'v3.2', 'version', 'v3.3', 'Which version is used by the {name} event schema?'),
    'compression_ratio': ('archive compressor', '0.75', 'ratio', '0.8', 'What ratio is configured for the {name} archive compressor?'),
    'metrics_port': ('metrics listener', '9107', 'port', '9108', 'On which port does the {name} metrics listener accept connections?'),
    'validation_enum': ('input validator', 'strict', 'mode', 'lenient', 'Name the mode selected for the {name} input validator.'),
    'request_timeout': ('outbound request', '45', 'seconds', '50', 'After how many seconds does the {name} outbound request time out?'),
    'settlement_currency': ('settlement ledger', 'JPY', 'currency', 'USD', 'Which currency does the {name} settlement ledger use?'),
    'parcel_weight': ('standard parcel', '12.5', 'kg', '13.5', 'What is the weight, in kg, of the {name} standard parcel?'),
    'retention_days': ('audit archive', '7', 'days', '9', 'For how many days does the {name} audit archive retain entries?'),
    'queue_order': ('dispatch queue', 'fifo', 'ordering', 'lifo', 'What ordering policy does the {name} dispatch queue follow?'),
}


PROFILES = ('kestrel', 'harbor', 'juniper', 'basalt', 'cobalt', 'lantern', 'meridian', 'quarry',
            'saffron', 'tundra', 'willow', 'zephyr')
