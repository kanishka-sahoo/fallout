MATCH (r:Repo {key: $repo})-[o:OVERRIDES]->(p:Package)
WHERE p.name IN $affected_packages
RETURN p.name AS pkg, o.spec AS spec, o.parent AS parent, o.resolved_version AS resolved_version
