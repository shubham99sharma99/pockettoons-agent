-- Faithful, typed copy of raw.sessions. No business logic: cleaning decisions are made
-- downstream (and by the analyst/agent), never silently here.
select * from {{ source('raw', 'sessions') }}
