MATCH (:Incident {id: $incident})-[:INCLUDES]->(a:Advisory)-[:AFFECTS]->(v:Version)
OPTIONAL MATCH (p:Package)-[:HAS_VERSION]->(v)
RETURN DISTINCT v.key AS key, a.id AS advisory, v.published_at AS published_at,
       p.weekly_downloads AS downloads
