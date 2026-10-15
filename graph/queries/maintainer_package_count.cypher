MATCH (m:Maintainer)-[:MAINTAINS]->(p:Package)
WITH m, count(p) AS n
SET m.package_count = n
