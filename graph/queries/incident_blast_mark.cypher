// Records that the blast radius ran, so "no EXPOSES edges" reads as "nothing exposed".
MATCH (i:Incident {id: $incident})
SET i.blast_at = $now, i.exposed_versions = $exposed
