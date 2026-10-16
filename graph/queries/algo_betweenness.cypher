// BUILD.md §7.6. Sampled, with a fixed seed so the scores are reproducible.
CALL algo.betweenness({nodeLabels: ['Package'], relationshipTypes: ['PKG_DEPENDS_ON'],
                       samplingSize: 256, samplingSeed: 42})
YIELD node, score
SET node.betweenness = score
