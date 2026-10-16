// BUILD.md §7.7 step 1: maintainers ranked by summed PageRank over their packages.
MATCH (m:Maintainer)-[:MAINTAINS]->(p:Package)
WHERE p.pagerank IS NOT NULL
WITH m, sum(p.pagerank) AS pr, collect(p.name) AS packages
RETURN m.name AS maintainer, pr, packages
ORDER BY pr DESC LIMIT $k
