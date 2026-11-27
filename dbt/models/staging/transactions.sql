-- Faithful copy of raw.transactions. amount_usd is passed through unchanged:
-- the documented convention is "charges positive, refunds negative". The
-- `assert_refunds_negative` data test checks that convention instead of
-- silently "fixing" values here.
select
    txn_id,
    user_id,
    date,
    created_at,
    type,
    amount_usd,
    payment_method,
    status
from {{ source('raw', 'transactions') }}
