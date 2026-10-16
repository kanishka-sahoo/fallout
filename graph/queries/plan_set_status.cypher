// Compare-and-set: only moves a plan out of the status the caller saw.
MATCH (p:Plan {id: $id})
WHERE p.status IN $from
SET p.status = $to, p.updated_at = $now
RETURN p.status AS status
