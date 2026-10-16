// Deletes a simulated incident, its advisories and the versions it invented. The edges go first
// (can_resolve_clear, exposes_clear).
MATCH (i:Incident {id: $incident}) WHERE i.simulated = true
OPTIONAL MATCH (i)-[:INCLUDES]->(a:Advisory)
OPTIONAL MATCH (a)-[:AFFECTS]->(v:Version)
WHERE v.simulated = true
DETACH DELETE v, a, i
