// Returns the repo's locked versions. With no match, OPTIONAL MATCH and collect give {key: null}. Python drops that row.
MATCH (r:Repo {key: $repo})
OPTIONAL MATCH (r)-[l:LOCKS]->(v:Version)
WHERE v.name IN $affected_packages
RETURN r.has_lockfile AS has_lockfile, collect({key: v.key, path: l.path}) AS locked
