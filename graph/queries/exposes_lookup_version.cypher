// Returns the parent pointer of one exposed Version.
MATCH (n:Version {key: $key})<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN x.via AS via, x.hop AS hop
