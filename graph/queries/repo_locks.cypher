// A locked version the crawl never resolved still gets a node, so LOCKED_MALICIOUS and
// lock-safe checks can see it. It has no DEPENDS_ON edges, so traversal ignores it.
UNWIND $rows AS row
MERGE (p:Package {name: row.name})
MERGE (v:Version {key: row.key})
  ON CREATE SET v.name = row.name, v.version = row.version, v.is_malicious = false,
                v.deprecated = false, v.from_lockfile = true
MERGE (p)-[:HAS_VERSION]->(v)
WITH v, row
MATCH (r:Repo {key: $key})
CREATE (r)-[:LOCKS {path: row.path}]->(v)
