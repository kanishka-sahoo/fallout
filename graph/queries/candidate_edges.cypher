// Finds every Version or Repo with an edge into an affected package, and the version that the edge
// resolves to at S. Malicious versions have no incoming edges yet, so `t` is never a malicious version.
UNWIND $packages AS pkg
MATCH (:Package {name: pkg})-[:HAS_VERSION]->(t:Version)<-[e:DEPENDS_ON|DIRECT_DEP]-(d)
RETURN pkg, d.key AS dependent, labels(d)[0] AS kind, e.requirement AS requirement, t.version AS at_s
