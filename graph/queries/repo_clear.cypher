// A re-parse replaces DIRECT_DEP, LOCKS and OVERRIDES (BUILD.md §4.2).
MATCH (r:Repo {key: $key})-[e:DIRECT_DEP|LOCKS|OVERRIDES]->()
DELETE e
