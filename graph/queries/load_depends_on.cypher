UNWIND $rows AS r
MATCH (a:Version {key: r.from}), (b:Version {key: r.to})
MERGE (a)-[e:DEPENDS_ON]->(b)
  ON CREATE SET e.requirement = r.requirement, e.kind = r.kind
