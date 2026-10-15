MERGE (r:Repo {key: $key})
SET r.full_name = $full_name, r.default_branch = $default_branch, r.head_sha = $head_sha,
    r.has_lockfile = $has_lockfile, r.lockfile_version = $lockfile_version
