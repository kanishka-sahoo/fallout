MATCH (p:Plan) WHERE p.incident = $incident
DETACH DELETE p
