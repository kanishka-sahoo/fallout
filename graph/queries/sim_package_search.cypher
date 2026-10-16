// Package name search for the scenario builder. Exact matches first, then by weekly downloads.
MATCH (p:Package)
WHERE p.name STARTS WITH $q
RETURN p.name AS name, p.weekly_downloads AS downloads
ORDER BY CASE WHEN p.name = $q THEN 0 ELSE 1 END, coalesce(p.weekly_downloads, 0) DESC
LIMIT $k
