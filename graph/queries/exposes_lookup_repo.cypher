// Returns the parent pointer of one exposed Repo.
MATCH (n:Repo {key: $key})<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN x.via AS via, x.hop AS hop
