// Returns the incident's affected versions as ingest_advisory wrote them. Per-repo rechecks use them.
MATCH (:Incident {id: $incident})-[:INCLUDES]->(a:Advisory)-[:AFFECTS]->(v:Version)
RETURN a.id AS advisory, v.name AS name, v.version AS version, v.key AS key,
       a.kind = 'MALICIOUS' AS malicious, v.published_at AS published_at
