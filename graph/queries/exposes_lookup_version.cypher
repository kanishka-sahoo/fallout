// Parent pointer of one exposed Version (BUILD.md §7.4).
MATCH (n:Version {key: $key})<-[x:EXPOSES]-(:Incident {id: $incident})
RETURN x.via AS via, x.hop AS hop
