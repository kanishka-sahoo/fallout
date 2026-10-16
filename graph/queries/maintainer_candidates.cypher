// Maintainer reach, step 1. Ranks maintainers by the sum of PageRank over their packages.
MATCH (m:Maintainer)-[:MAINTAINS]->(p:Package)
WHERE p.pagerank IS NOT NULL
WITH m, sum(p.pagerank) AS pr, collect(p.name) AS packages
RETURN m.name AS maintainer, pr, packages
ORDER BY pr DESC LIMIT $k
