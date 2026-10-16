// Same as candidate_edges, but only for one repo's own requirements. recheck_repo uses it after a manifest change.
MATCH (d:Repo {key: $repo})-[e:DIRECT_DEP]->(t:Version)
WHERE t.name IN $packages
RETURN t.name AS pkg, d.key AS dependent, 'Repo' AS kind, e.requirement AS requirement, t.version AS at_s
