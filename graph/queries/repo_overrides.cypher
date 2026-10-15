UNWIND $rows AS row
MERGE (p:Package {name: row.name})
WITH p, row
MATCH (r:Repo {key: $key})
CREATE (r)-[o:OVERRIDES]->(p)
SET o.spec = row.spec, o.parent = row.parent, o.resolved_version = row.resolved_version
