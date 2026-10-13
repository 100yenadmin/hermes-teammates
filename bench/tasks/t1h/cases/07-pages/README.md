# Cursor pagination

Pure Python service; put src on the import path. Inputs follow these contracts. Review supported behavior violations without editing.

Keys are (timestamp,id), both integer, lexicographic. Cursor is exclusive on both fields. page_query.page filters after cursor and sorts ascending then takes exact limit (zero returns none). merging.unique removes overlap by ID keeping first row and preserving order. page_client.advance returns last full key or None for an empty page. combine gives first-page precedence. Empty input is valid.
