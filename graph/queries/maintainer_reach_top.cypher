MATCH (m:Maintainer) WHERE m.reach_packages IS NOT NULL
OPTIONAL MATCH (m)-[:MAINTAINS]->(p:Package)
WITH m, count(p) AS owned,
     [x IN collect(p) WHERE x.maintainer_count = 1 | x.name] AS sole_maintainer_of
RETURN m.name AS maintainer, m.reach_packages AS reach_packages, m.reach_downloads AS reach_downloads,
       owned AS packages_maintained, size(sole_maintainer_of) AS sole_maintainer_count
ORDER BY reach_packages DESC LIMIT $k
