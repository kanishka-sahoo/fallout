UNWIND $rows AS row
MATCH (r:Repo {key: $key}), (v:Version {key: row.to})
MERGE (r)-[e:DIRECT_DEP]->(v)
SET e.requirement = row.requirement, e.scope = row.scope
