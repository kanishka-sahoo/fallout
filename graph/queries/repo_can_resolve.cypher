// Returns CAN_RESOLVE_TO edges from the repo or from any version in its transitive dependency tree.
MATCH (r:Repo {key: $repo})-[c:CAN_RESOLVE_TO]->(m:Version)
WHERE c.incident = $incident
RETURN r.key AS dependent, m.name AS pkg, m.key AS target, c.requirement AS requirement
UNION
UNWIND $keys AS k
MATCH (v:Version {key: k})-[c:CAN_RESOLVE_TO]->(m:Version)
WHERE c.incident = $incident
RETURN v.key AS dependent, m.name AS pkg, m.key AS target, c.requirement AS requirement
