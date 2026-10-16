// Writes one repo's EXPOSES edge after a recheck. A null hop means the ranges no longer reach it.
// The edge stays because it holds the status (for example MITIGATED_BY_OVERRIDE).
MATCH (i:Incident {id: $incident}), (r:Repo {key: $repo})
MERGE (i)-[x:EXPOSES]->(r)
SET x.hop = $hop, x.via = $via, x.status = $status, x.status_updated_at = $now
