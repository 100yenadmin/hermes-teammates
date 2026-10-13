# Access policy queries

Pure Python service; use src on the import path. Inputs obey the domains below unless a rejection rule is stated. Public entry points compose the named helpers. Review concrete observable violations of this contract. Do not edit files.

A grant is permitted only if some group allows it and no group denies it. cache decisions include user, action, revision, and group snapshot; revision always advances on change. query.check uses all groups. Unknown actions are denied. Empty all_enabled is true; group names are case-sensitive; a cached false is a valid cache hit; merge returns fresh sets.
