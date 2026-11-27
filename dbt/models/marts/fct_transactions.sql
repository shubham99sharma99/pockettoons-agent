-- Transactions enriched with the user's country and acquisition source.
select t.*, u.country, u.acquisition_source
from {{ ref('transactions') }} t
join {{ ref('users') }} u using (user_id)
