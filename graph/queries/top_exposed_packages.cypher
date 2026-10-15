MATCH (:Incident {id: $incident})-[:EXPOSES]->(v:Version)<-[:HAS_VERSION]-(p:Package)
WHERE p.weekly_downloads IS NOT NULL
WITH DISTINCT p
RETURN p.name AS package, p.weekly_downloads AS downloads
ORDER BY downloads DESC LIMIT $k
