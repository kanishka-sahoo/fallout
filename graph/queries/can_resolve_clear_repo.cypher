MATCH (:Repo {key: $repo})-[c:CAN_RESOLVE_TO]->(:Version)
WHERE c.incident = $incident
DELETE c
