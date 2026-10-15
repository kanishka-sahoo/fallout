UNWIND $rows AS row
MATCH (d:Version {key: row.dependent}), (m:Version {key: row.to})
MERGE (d)-[c:CAN_RESOLVE_TO {incident: $incident}]->(m)
SET c.requirement = row.requirement
