// Reads the stored centrality scores. $order is pagerank or betweenness.
MATCH (p:Package) WHERE p.pagerank IS NOT NULL
RETURN p.name AS package, p.pagerank AS pagerank, p.betweenness AS betweenness,
       p.weekly_downloads AS downloads, p.maintainer_count AS maintainers,
       p.has_provenance AS has_provenance
ORDER BY CASE $order WHEN 'betweenness' THEN p.betweenness ELSE p.pagerank END DESC LIMIT $k
