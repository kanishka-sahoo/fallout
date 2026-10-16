MATCH (r:Repo {key: $key})
SET r.checked_ref = $ref, r.head_sha = coalesce($sha, r.head_sha)
