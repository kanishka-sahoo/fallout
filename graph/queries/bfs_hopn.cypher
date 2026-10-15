// BUILD.md §7.3, hops 2..N: everything resolved at S onto an exposed version. Repos are terminal.
UNWIND $frontier AS k
MATCH (v:Version {key: k})<-[:DEPENDS_ON|DIRECT_DEP]-(u)
RETURN DISTINCT k AS via, u.key AS node, labels(u)[0] AS kind
