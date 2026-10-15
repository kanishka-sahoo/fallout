// BUILD.md §7.1: every Version or Repo with an edge into an affected package, plus the
// version it resolves to at S. Malicious versions have no incoming edges yet, so `t` is never one.
UNWIND $packages AS pkg
MATCH (:Package {name: pkg})-[:HAS_VERSION]->(t:Version)<-[e:DEPENDS_ON|DIRECT_DEP]-(d)
RETURN pkg, d.key AS dependent, labels(d)[0] AS kind, e.requirement AS requirement, t.version AS at_s
