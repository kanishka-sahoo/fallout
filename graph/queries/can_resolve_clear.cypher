MATCH ()-[c:CAN_RESOLVE_TO]->()
WHERE c.incident = $incident
DELETE c
