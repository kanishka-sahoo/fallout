// The persisted blast-radius result for one repo; no row or a null hop means the ranges never reach it.
MATCH (r:Repo {key: $repo})
OPTIONAL MATCH (r)<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN r.key AS key, x.hop AS hop, x.via AS via, x.status AS status
