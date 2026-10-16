// A remediation plan (BUILD.md §6.3 step 1). Not in the §4.1 schema: plans have to outlive the
// MCP server process, and the approval endpoint and executor read them from here.
MATCH (r:Repo {key: $repo})
MERGE (p:Plan {id: $id})
SET p.repo = $repo, p.incident = $incident, p.status = $status, p.created_at = $now,
    p.updated_at = $now, p.body = $body
MERGE (p)-[:FOR]->(r)
