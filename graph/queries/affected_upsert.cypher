// Malicious versions never existed at S, so they are created here (BUILD.md §5.3). A stub
// made earlier from a lockfile (LOCKED_MALICIOUS) is the same node and is upgraded in place.
UNWIND $rows AS row
MERGE (p:Package {name: row.name})
MERGE (v:Version {key: row.key})
  ON CREATE SET v.name = row.name, v.version = row.version, v.deprecated = false,
                v.is_malicious = false
SET v.is_malicious = v.is_malicious OR row.malicious,
    v.published_at = coalesce(row.published_at, v.published_at)
MERGE (p)-[:HAS_VERSION]->(v)
WITH v, row
MATCH (a:Advisory {id: row.advisory})
MERGE (a)-[:AFFECTS]->(v)
