// Returns the requirement on one hop of an exposure path that starts at a Version.
MATCH (a:Version {key: $from})-[e:DIRECT_DEP|DEPENDS_ON|CAN_RESOLVE_TO]->(b:Version {key: $to})
WHERE type(e) <> 'CAN_RESOLVE_TO' OR e.incident = $incident
RETURN type(e) AS type, e.requirement AS requirement
LIMIT 1
