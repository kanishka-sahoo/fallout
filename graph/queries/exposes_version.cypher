UNWIND $rows AS r
MATCH (i:Incident {id: $incident}), (v:Version {key: r.node})
MERGE (i)-[x:EXPOSES]->(v)
SET x.hop = r.hop, x.via = r.via
