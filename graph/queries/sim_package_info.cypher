// Weekly downloads, maintainers and the number of direct dependents (versions and repos) of one package.
MATCH (p:Package {name: $name})
OPTIONAL MATCH (p)-[:HAS_VERSION]->(:Version)<-[:DEPENDS_ON|DIRECT_DEP]-(d)
WITH p, count(DISTINCT d) AS dependents
OPTIONAL MATCH (m:Maintainer)-[:MAINTAINS]->(p)
RETURN p.name AS name, p.weekly_downloads AS downloads, dependents, collect(m.name) AS maintainers
