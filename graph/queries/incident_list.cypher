MATCH (i:Incident)
RETURN i.id AS id, i.title AS title, i.started_at AS started_at, i.blast_at AS blast_at,
       i.exposed_versions AS exposed
ORDER BY id
