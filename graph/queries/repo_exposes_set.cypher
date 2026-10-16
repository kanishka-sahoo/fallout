// One repo's EXPOSES edge after a recheck. A null hop means the ranges no longer reach it;
// the edge stays so the status (e.g. MITIGATED_BY_OVERRIDE) has somewhere to live.
MATCH (i:Incident {id: $incident}), (r:Repo {key: $repo})
MERGE (i)-[x:EXPOSES]->(r)
SET x.hop = $hop, x.via = $via, x.status = $status, x.status_updated_at = $now
