UNWIND $rows AS r
MATCH (i:Incident {id: $incident}), (repo:Repo {key: r.node})
MERGE (i)-[x:EXPOSES]->(repo)
SET x.hop = r.hop, x.via = r.via
