// BUILD.md §7.5. OPTIONAL MATCH + collect yields {key: null} when nothing matches; Python drops it.
MATCH (r:Repo {key: $repo})
OPTIONAL MATCH (r)-[l:LOCKS]->(v:Version)
WHERE v.name IN $affected_packages
RETURN r.has_lockfile AS has_lockfile, collect({key: v.key, path: l.path}) AS locked
