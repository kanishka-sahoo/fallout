// Returns the stored blast radius as a parent-pointer tree. The console draws its graph from it.
MATCH (i:Incident {id: $incident})-[x:EXPOSES]->(n)
WHERE x.hop IS NOT NULL
OPTIONAL MATCH (p:Package)-[:HAS_VERSION]->(n)
RETURN n.key AS key, labels(n)[0] AS kind, x.hop AS hop, x.via AS via, x.status AS status,
       p.weekly_downloads AS downloads
