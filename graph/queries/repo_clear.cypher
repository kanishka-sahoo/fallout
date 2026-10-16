// Deletes DIRECT_DEP, LOCKS and OVERRIDES edges before a re-parse writes new ones.
MATCH (r:Repo {key: $key})-[e:DIRECT_DEP|LOCKS|OVERRIDES]->()
DELETE e
