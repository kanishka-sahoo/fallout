// Flags a simulated incident and the versions it invented, so deleting the scenario removes them.
MATCH (i:Incident {id: $incident})
SET i.simulated = true, i.scenario = $scenario, i.created_at = $now
WITH i
UNWIND $keys AS key
MATCH (v:Version {key: key})
SET v.simulated = true
