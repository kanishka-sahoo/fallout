MATCH (p:Plan)
WHERE $status IS NULL OR p.status = $status
RETURN p.id AS id, p.repo AS repo, p.incident AS incident, p.status AS status, p.body AS body,
       p.created_at AS created_at, p.updated_at AS updated_at
ORDER BY p.created_at DESC
