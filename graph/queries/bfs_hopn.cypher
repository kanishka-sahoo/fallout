// Blast radius, hops 2..N. Finds every node that resolved at S to an exposed version. Repos are leaf nodes.
UNWIND $frontier AS k
MATCH (v:Version {key: k})<-[:DEPENDS_ON|DIRECT_DEP]-(u)
RETURN DISTINCT k AS via, u.key AS node, labels(u)[0] AS kind
