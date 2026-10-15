// Parent pointer of one exposed Repo (BUILD.md §7.4).
MATCH (n:Repo {key: $key})<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN x.via AS via, x.hop AS hop
