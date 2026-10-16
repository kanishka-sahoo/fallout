// Betweenness centrality over the package graph. It is sampled with a fixed seed, so the scores are reproducible.
CALL algo.betweenness({nodeLabels: ['Package'], relationshipTypes: ['PKG_DEPENDS_ON'],
                       samplingSize: 256, samplingSeed: 42})
YIELD node, score
SET node.betweenness = score
