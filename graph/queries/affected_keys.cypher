MATCH (:Incident {id: $incident})-[:INCLUDES]->(a:Advisory)-[:AFFECTS]->(v:Version)
RETURN DISTINCT v.key AS key, v.name AS name, v.version AS version
