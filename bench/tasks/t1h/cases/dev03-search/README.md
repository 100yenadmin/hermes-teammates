# Document search

Pure Python service; put src on the import path. Review supported behavior violations without editing.

Tokens lowercase and split arbitrary whitespace. Index retains all token document IDs. searching.find requires all query tokens; empty query no results. ranking.top sorts score descending then ID ascending, exact limit, zero empty. IDs case-sensitive; repeated posting idempotent; unknown token no hits.
