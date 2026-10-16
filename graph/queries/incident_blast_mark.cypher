// Records that the blast radius ran. After this, "no EXPOSES edges" means "nothing exposed".
MATCH (i:Incident {id: $incident})
SET i.blast_at = $now, i.exposed_versions = $exposed
