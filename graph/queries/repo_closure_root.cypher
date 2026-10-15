MATCH (r:Repo {key: $repo})-[e:DIRECT_DEP]->(u:Version)
RETURN u.key AS node, u.name AS name, e.requirement AS requirement
