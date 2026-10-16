// Malicious versions did not exist at S, so this query creates them. A lockfile can create a
// stub node earlier (LOCKED_MALICIOUS). That stub is the same node, and this query updates it.
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
