UNWIND $rows AS r
MERGE (p:Package {name: r.name})
MERGE (v:Version {key: r.key})
  ON CREATE SET v.name = r.name, v.version = r.version,
                v.published_at = r.published_at, v.deprecated = r.deprecated,
                v.is_malicious = false
MERGE (p)-[:HAS_VERSION]->(v)
