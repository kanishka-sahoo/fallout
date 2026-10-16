// Returns the stored blast-radius result for one repo. No row or a null hop means the ranges do not reach it.
MATCH (r:Repo {key: $repo})
OPTIONAL MATCH (r)<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN r.key AS key, x.hop AS hop, x.via AS via, x.status AS status
