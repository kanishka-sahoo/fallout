// Re-derive one repo's BFS entry after its manifest changed (recheck_repo): hop 1 when the repo
// itself would resolve to an affected version, else one past its nearest exposed direct dep.
MATCH (r:Repo {key: $repo})
OPTIONAL MATCH (r)-[c:CAN_RESOLVE_TO]->(m:Version)
WHERE c.incident = $incident
OPTIONAL MATCH (r)-[:DIRECT_DEP]->(v:Version)<-[x:EXPOSES]-(:Incident {id: $incident})
WITH r, collect(DISTINCT m.key) AS direct_hits, collect(DISTINCT {via: v.key, hop: x.hop}) AS deps
RETURN direct_hits, [d IN deps WHERE d.via IS NOT NULL] AS deps
