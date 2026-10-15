MERGE (i:Incident {id: $id})
SET i.title = $title, i.started_at = $started_at, i.status = coalesce(i.status, 'OPEN')
