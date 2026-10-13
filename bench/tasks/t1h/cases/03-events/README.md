# Event ingestion

Pure Python service; use src on the import path. Inputs obey the domains below unless a rejection rule is stated. Public entry points compose the named helpers. Review concrete observable violations of this contract. Do not edit files.

parse_event converts local minute to UTC by subtracting signed offset_minutes. normalize trims and lowercases kind but preserves payload case. Dedupe identity is (source,id); first occurrence wins. store.ingest deduplicates then stably sorts by UTC minute and returns all rows; a zero limit returns none. Missing payload becomes empty text. Source names are case-sensitive.
