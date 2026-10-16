MATCH (i:Incident)
RETURN i.id AS id, i.title AS title, i.started_at AS started_at, i.blast_at AS blast_at,
       i.exposed_versions AS exposed, coalesce(i.simulated, false) AS simulated, i.scenario AS scenario,
       i.created_at AS created_at
ORDER BY id
