// Compare-and-set. Changes the plan status only if it still has the status that the caller read.
MATCH (p:Plan {id: $id})
WHERE p.status IN $from
SET p.status = $to, p.updated_at = $now
RETURN p.status AS status
