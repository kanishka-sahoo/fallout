// The packages of the maintainer account with the widest reach, most downloaded first.
MATCH (m:Maintainer) WHERE m.reach_packages IS NOT NULL
WITH m ORDER BY m.reach_packages DESC LIMIT 1
MATCH (m)-[:MAINTAINS]->(p:Package)
RETURN m.name AS maintainer, m.reach_packages AS reach, p.name AS name, p.weekly_downloads AS downloads
ORDER BY coalesce(p.weekly_downloads, 0) DESC
LIMIT $k
