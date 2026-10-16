// Advisories of an incident that affect the given packages (PR body links).
MATCH (:Incident {id: $incident})-[:INCLUDES]->(a:Advisory)-[:AFFECTS]->(v:Version)
WHERE v.name IN $packages
RETURN DISTINCT a.id AS id, a.url AS url, a.summary AS summary, v.name AS package, v.version AS version
ORDER BY package
