UNWIND $rows AS row
MERGE (m:Maintainer {name: row.maintainer})
WITH m, row
MATCH (p:Package {name: row.package})
MERGE (m)-[:MAINTAINS]->(p)
