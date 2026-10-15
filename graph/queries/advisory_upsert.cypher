UNWIND $rows AS row
MERGE (a:Advisory {id: row.id})
SET a.kind = row.kind, a.summary = row.summary, a.published_at = row.published_at,
    a.severity = row.severity, a.url = row.url
WITH a
MATCH (i:Incident {id: $incident})
MERGE (i)-[:INCLUDES]->(a)
