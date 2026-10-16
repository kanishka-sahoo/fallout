// Every demo repo with its status for one incident. A repo with no EXPOSES edge is not affected.
MATCH (r:Repo)
OPTIONAL MATCH (:Incident {id: $incident})-[x:EXPOSES]->(r)
RETURN r.key AS repo, x.status AS status
