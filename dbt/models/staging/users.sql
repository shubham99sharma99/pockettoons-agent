-- Faithful, typed copy of raw.users. No business logic: cleaning decisions are made
-- downstream (and by the analyst/agent), never silently here.
select * from {{ source('raw', 'users') }}
