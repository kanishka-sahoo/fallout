UNWIND $rows AS row
MERGE (m:Maintainer {name: row.maintainer})
WITH m, row
MATCH (v:Version {key: row.key})
MERGE (m)-[:PUBLISHED]->(v)
