// Directed PageRank. A package scores by its incoming PKG_DEPENDS_ON edges (its dependents).
CALL algo.pageRank('Package', 'PKG_DEPENDS_ON') YIELD node, score
SET node.pagerank = score
