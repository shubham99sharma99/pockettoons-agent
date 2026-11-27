-- Data contract: refunds must be stored as negative amounts (the documented
-- convention). Returns offending rows grouped by month x payment_method.
-- Configured as a warning so the pipeline still builds, but the failure is
-- visible in `dbt build` output and CI. This is the check that would have
-- caught the billing-integration bug before an analyst did.
{{ config(severity='warn') }}
select date_trunc('month', date) as month, payment_method, count(*) as positive_refunds
from {{ ref('transactions') }}
where type = 'refund' and amount_usd > 0
group by 1, 2
