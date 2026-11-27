-- Faithful, typed copy of raw.content_catalog. No business logic: cleaning decisions are made
-- downstream (and by the analyst/agent), never silently here.
select * from {{ source('raw', 'content_catalog') }}
