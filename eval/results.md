# Eval results

Run 2026-11-27T22:59:35+00:00 · provider `nim` · agent `nvidia/nemotron-3-ultra-550b-a55b` · judge `nvidia/nemotron-3.5-super-vl-120b-a12b`

**20 / 21 passed (95%).** Median latency 41.52 s, median tool calls 8, median tokens in/out 69392/2921.

| ID | Category | Question | Expected | Agent headline | Result | Failure type | Tools |
|---|---|---|---|---|---|---|---|
| E01 | simple | What was MAU in October 2026? | 1.506e+04 | MAU in October 2026 was 15,057 users | PASS | none | 4 |
| E02 | simple | How many subscribers were active on 30 Nov 2026? | 2,835 | 2,835 active subscribers on 30 Nov 2026 | PASS | none | 6 |
| E03 | simple | What was total PPV revenue in Q2? | 8,445 | Total PPV revenue in Q2 was $8,445.45 | PASS | none | 11 |
| E04 | filtered | How many US users started a subscription in September 2026? | 595 | 593 US users started a subscription in September 2026 | PASS | none | 7 |
| E05 | filtered | What share of sessions in Brazil were on Android in November 2026? | 0.8337 | 83.4% of sessions in Brazil were on Android in November 2026 | PASS | none | 7 |
| E06 | filtered | Split Q2 PPV revenue into paywall unlocks and premium episodes. How mu | 2,386 | Q2 PPV revenue: $8,445.45 total, $2,385.90 (28.3%) from paywall unlocks | PASS | none | 5 |
| E07 | time | How did MAU change from September to October 2026? | 0.04621 | MAU grew 4.6% from September (14,392) to October (15,057) 2026 | PASS | none | 5 |
| E08 | time | How did PPV revenue change from Q1 to Q2? | -0.2834 | PPV revenue fell 28.3% QoQ (Q1 $11,785 → Q2 $8,445), driven by a 64% collapse in standard-tier ($0.99) unlocks while premium-tier ($1.99) gr | PASS | none | 8 |
| E09 | time | Which channel's spend grew most from July to October 2026? | rubric | TikTok Ads spend grew most from July to October 2026 (+$7,156, +209%) | PASS | none | 5 |
| E10 | cohort | Compare D30 retention for the June and September 2026 signup cohorts. | rubric | D30 retention fell 0.88 pp from June (13.13%) to September (12.25%); ~60% of the drop is mix shift toward lower-retention countries and paid | PASS | none | 11 |
| E11 | cohort | What share of the August 2026 signup cohort paid within 30 days, by ch | rubric | August 2026 cohort 30-day payer rate by channel: meta_ads 29.8%, google_ads 28.8%, referral 24.0%, organic 23.5%, influencer 14.1%, tiktok_a | PASS | none | 5 |
| E12 | cohort | What was the cost per paying user by channel for Q2 signups? | rubric | Cost per paying user (30-day) for Q2 signups: google_ads $33.10, meta_ads $37.24, tiktok_ads $37.60, influencer $40.56; organic/referral $0 | PASS | none | 9 |
| E13 | ambiguous | How are we doing in LatAm? | rubric | LatAm MAU +66% but payer rate –3.1 pp; revenue +51% driven by volume, not quality. September marketing pivot to influencer/TikTok brought lo | PASS | none | 14 |
| E14 | ambiguous | Is the free tier too generous? | rubric | The free tier increase from 5 to 8 episodes/day coincided with a 23% payer rate drop and 19% revenue-per-MAU decline, though acquisition mix | PASS | none | 21 |
| E15 | unanswerable | What is revenue by user gender? | rubric | Gender data is not available in the database | FAIL | other | 8 |
| E16 | unanswerable | Why did subscribers cancel? | rubric | 98.7% of cancellations are voluntary, with 59.8% occurring exactly at day 30 (first billing cycle); voluntary churners show 60% lower engage | PASS | none | 20 |
| E17 | dq_trap | What was total net revenue from June to November 2026? | 1.933e+05 | Total net revenue June–November 2026 was $193,339.17 after correcting a refund sign issue. | PASS | none | 10 |
| E18 | dq_trap | What was the refund rate by month? | rubric | Refund rate by month: 4.4%–5.4% (Jun–Nov 2026), lowest in Aug/Oct (~4.4%), peak in Sep (5.4%) | PASS | none | 8 |
| E19 | dq_trap | Is Android checkout broken? | rubric | Android checkout is not broken; Google Play failure rates (3.2–3.6%) match App Store and card, and the lower Android payer rate is due to ac | PASS | none | 20 |
| E20 | premise_check | Why did revenue grow in Q2? | rubric | Revenue fell 3.5% in Q2 (Sep–Nov) vs Q1 (Jun–Aug), driven by a channel mix shift to TikTok/Influencer (low payer rates) and collapsing payer | PASS | none | 14 |
| E21 | end_to_end | MAU is up 20% QoQ but revenue is flat. Board meeting Thursday. Figure  | rubric | MAU +20% but revenue −6.5% QoQ: free-limit increase (5→8) cannibalised PPV, paid-channel mix shifted to low-payer-rate TikTok/influencer, an | PASS | none | 22 |

## By category

| Category | Passed |
|---|---|
| simple | 3/3 |
| filtered | 3/3 |
| time | 3/3 |
| cohort | 3/3 |
| ambiguous | 2/2 |
| unanswerable | 1/2 |
| dq_trap | 3/3 |
| premise_check | 1/1 |
| end_to_end | 1/1 |

## Failure analysis

- **E15** (other): The answer correctly states there is no gender column and does not fabricate a gender split or infer gender from names, and it reports no gender-level numbers. However, the rubric requires offering an available alternative cut (e.g., country or channel) labelled as such; the agent only notes that country/acquisition_source exist but does not offer revenue by country/channel as an alternative. It therefore avoids the hard fail but does not fully satisfy the pass criteria.
