UNWIND $names AS n
MATCH (a:Package {name: n})-[:HAS_VERSION]->(:Version)-[:DEPENDS_ON]->(:Version)<-[:HAS_VERSION]-(b:Package)
WHERE a <> b
WITH DISTINCT a, b
MERGE (a)-[:PKG_DEPENDS_ON]->(b)
