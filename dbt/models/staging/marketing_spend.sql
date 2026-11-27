-- Faithful, typed copy of raw.marketing_spend. No business logic: cleaning decisions are made
-- downstream (and by the analyst/agent), never silently here.
select * from {{ source('raw', 'marketing_spend') }}
