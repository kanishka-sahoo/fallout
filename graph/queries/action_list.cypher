MATCH (a:Action)-[:ON]->(r:Repo)
RETURN a.id AS id, a.type AS type, a.created_at AS created_at, a.approved_by AS approved_by,
       a.plan_id AS plan_id, a.pr_url AS pr_url, a.result AS result, r.key AS repo
ORDER BY a.created_at DESC
