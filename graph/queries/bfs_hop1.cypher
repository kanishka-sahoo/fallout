// Blast radius, hop 1. Finds dependents that would resolve to an affected version.
UNWIND $frontier AS k
MATCH (m:Version {key: k})<-[c:CAN_RESOLVE_TO]-(u)
WHERE c.incident = $incident
RETURN DISTINCT k AS via, u.key AS node, labels(u)[0] AS kind
