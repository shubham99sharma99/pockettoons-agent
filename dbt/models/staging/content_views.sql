-- Faithful, typed copy of raw.content_views. No business logic: cleaning decisions are made
-- downstream (and by the analyst/agent), never silently here.
select * from {{ source('raw', 'content_views') }}
