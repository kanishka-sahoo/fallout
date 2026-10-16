MATCH (i:Incident {id: $incident})
RETURN i.id AS id, i.title AS title, i.started_at AS started_at, i.blast_at AS blast_at
