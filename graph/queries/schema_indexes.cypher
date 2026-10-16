// Graph indexes. Write one statement per line. Run this file before loading data.
CREATE INDEX FOR (p:Package) ON (p.name)
CREATE INDEX FOR (v:Version) ON (v.key)
CREATE INDEX FOR (v:Version) ON (v.name)
CREATE INDEX FOR (m:Maintainer) ON (m.name)
CREATE INDEX FOR (a:Advisory) ON (a.id)
CREATE INDEX FOR (i:Incident) ON (i.id)
CREATE INDEX FOR (r:Repo) ON (r.key)
