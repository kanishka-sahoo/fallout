// BUILD.md §7.6. Directed; scores by incoming PKG_DEPENDS_ON edges (dependents).
CALL algo.pageRank('Package', 'PKG_DEPENDS_ON') YIELD node, score
SET node.pagerank = score
