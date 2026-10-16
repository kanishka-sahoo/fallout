// Returns all package-level edges. Maintainer reach runs a reverse BFS on them in memory.
MATCH (a:Package)-[:PKG_DEPENDS_ON]->(b:Package)
RETURN a.name AS dependent, b.name AS dependency
