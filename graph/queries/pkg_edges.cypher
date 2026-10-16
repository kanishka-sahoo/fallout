// The whole package projection, for in-memory reverse BFS (maintainer reach, §7.7).
MATCH (a:Package)-[:PKG_DEPENDS_ON]->(b:Package)
RETURN a.name AS dependent, b.name AS dependency
