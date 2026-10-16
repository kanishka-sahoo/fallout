MATCH (v:Version {key: $key})
OPTIONAL MATCH (v)<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN v.key AS key, x.hop AS hop
