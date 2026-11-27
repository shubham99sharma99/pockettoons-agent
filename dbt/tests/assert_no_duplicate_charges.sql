-- Data contract: no two successful charges for the same user, type and amount
-- within 5 minutes (gateway double-posts). Warn-level: ~0.1% double-posts are expected noise (about 100-150 pairs).
{{ config(severity='warn', warn_if='>250') }}
select a.txn_id, b.txn_id as dup_txn_id
from {{ ref('transactions') }} a
join {{ ref('transactions') }} b
  on a.user_id = b.user_id and a.type = b.type and a.amount_usd = b.amount_usd
 and a.status = 'success' and b.status = 'success' and a.txn_id < b.txn_id
 and abs(epoch(b.created_at) - epoch(a.created_at)) <= 300
where a.type <> 'refund'
