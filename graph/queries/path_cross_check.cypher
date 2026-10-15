// BUILD.md §7.4 cross-check. FalkorDB only allows shortestPath in WITH/RETURN (DECISIONS D2).
MATCH (r:Repo {key: $repo}), (m:Version {key: $malicious})
WITH shortestPath((r)-[:DIRECT_DEP|DEPENDS_ON|CAN_RESOLVE_TO*1..15]->(m)) AS p
WHERE p IS NOT NULL
RETURN [n IN nodes(p) | n.key] AS chain,
       [e IN relationships(p) | e.requirement] AS requirements,
       [e IN relationships(p) | e.incident] AS incidents
