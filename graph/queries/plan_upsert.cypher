// Stores a remediation plan. Plans are not in the original schema. They must persist after the MCP
// server process stops, because the approval endpoint and the fix executor read them from the graph.
MATCH (r:Repo {key: $repo})
MERGE (p:Plan {id: $id})
SET p.repo = $repo, p.incident = $incident, p.status = $status, p.created_at = $now,
    p.updated_at = $now, p.body = $body
MERGE (p)-[:FOR]->(r)
