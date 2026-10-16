// The repo status is a property of the EXPOSES edge. A LOCKED_MALICIOUS repo that the ranges do not
// reach still gets an edge with no hop, because the edge holds the status.
MATCH (i:Incident {id: $incident}), (r:Repo {key: $repo})
MERGE (i)-[x:EXPOSES]->(r)
SET x.status = $status, x.status_updated_at = $now
