UNWIND $rows AS r
MATCH (m:Maintainer {name: r.maintainer})
SET m.reach_packages = r.reach_packages, m.reach_downloads = r.reach_downloads,
    m.reach_rank_pagerank = r.pagerank
