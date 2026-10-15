MATCH (:Incident {id: $incident})-[x:EXPOSES]->()
DELETE x
