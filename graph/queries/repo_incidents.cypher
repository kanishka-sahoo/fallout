// The incidents that hold a status for one repo. They all read the repo's LOCKS and OVERRIDES edges.
MATCH (i:Incident)-[:EXPOSES]->(:Repo {key: $repo})
WHERE i.blast_at IS NOT NULL
RETURN DISTINCT i.id AS incident
