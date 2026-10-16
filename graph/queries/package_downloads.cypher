MATCH (p:Package)
RETURN p.name AS name, coalesce(p.weekly_downloads, 0) AS downloads
