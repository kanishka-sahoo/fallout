// Status lives on the EXPOSES edge (BUILD.md §4.2). A LOCKED_MALICIOUS repo the ranges never
// reach still gets an edge, with no hop, so the status has somewhere to live.
MATCH (i:Incident {id: $incident}), (r:Repo {key: $repo})
MERGE (i)-[x:EXPOSES]->(r)
SET x.status = $status, x.status_updated_at = $now
