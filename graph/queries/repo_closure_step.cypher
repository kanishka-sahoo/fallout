UNWIND $frontier AS k
MATCH (v:Version {key: k})-[e:DEPENDS_ON]->(u:Version)
RETURN k AS parent, u.key AS node, u.name AS name, e.requirement AS requirement
