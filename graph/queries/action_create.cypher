// Records an Action node for every write, as an audit trail.
MATCH (r:Repo {key: $repo}), (i:Incident {id: $incident})
CREATE (a:Action {id: $id, type: $type, created_at: $now, approved_by: $approved_by,
                  plan_id: $plan_id, pr_url: $pr_url, verification: $verification, result: $result})
CREATE (a)-[:ON]->(r), (a)-[:REMEDIATES]->(i)
RETURN a.id AS id
