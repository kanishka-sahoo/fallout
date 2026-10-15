UNWIND $rows AS row
MATCH (p:Package {name: row.name})
SET p.weekly_downloads = row.weekly_downloads, p.maintainer_count = row.maintainer_count,
    p.has_provenance = row.has_provenance
