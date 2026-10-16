// Deletes every record of one pull request: its Action nodes and the Plan it applied.
OPTIONAL MATCH (a:Action) WHERE a.pr_url = $pr_url
OPTIONAL MATCH (p:Plan {id: $plan})
DETACH DELETE a, p
