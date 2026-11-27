# Eval results

Run 2026-11-27T18:55:41+00:00 · provider `nim` · agent `nvidia/nemotron-3-ultra-550b-a55b` · judge `nvidia/nemotron-3.5-super-vl-120b-a12b`

**18 / 21 passed (86%).** Median latency 320.75 s, median tool calls 15, median tokens in/out 157301/11261.

| ID | Category | Question | Expected | Agent headline | Result | Failure type | Tools |
|---|---|---|---|---|---|---|---|
| E01 | simple | What was MAU in October 2026? | 1.506e+04 | **Answer:** MAU in October 2026 was **15,057** users. (Q1, Q2) | PASS | none | 4 |
| E02 | simple | How many subscribers were active on 30 Nov 2026? | 2,835 | **Answer:** 2,840 subscribers were active on 30 Nov 2026. (Q5) | PASS | none | 10 |
| E03 | simple | What was total PPV revenue in Q2? | 8,445 | **Answer:** Total PPV revenue in Q2 (Sep–Nov 2026) was **$8,445.45** (Q1). | PASS | none | 7 |
| E04 | filtered | How many US users started a subscription in September 2026? | 595 | 593 US users started a subscription in September 2026 (534 first-time, 59 resubscribers) | PASS | none | 34 |
| E05 | filtered | What share of sessions in Brazil were on Android in November 2026? | 0.8337 | **Answer:** 83.37% of sessions in Brazil were on Android in November 2026 (Q1). | PASS | none | 3 |
| E06 | filtered | Split Q2 PPV revenue into paywall unlocks and premium episodes. How mu | 2,386 | **Answer:** In Q2 (Sep–Nov 2026), **$2,385.90** of PPV revenue came from paywall unlocks (standard-tier episodes at $0.99 each). The remaini | PASS | none | 45 |
| E07 | time | How did MAU change from September to October 2026? | 0.04621 | **Answer:** MAU grew from 14,392 in September 2026 to 15,057 in October 2026, an increase of 665 users (+4.6%) (Q1). | PASS | none | 4 |
| E08 | time | How did PPV revenue change from Q1 to Q2? | -0.2834 | Gross PPV revenue fell 28.3% ($11.8k → $8.4k) from Q1 to Q2; net PPV revenue was flat (~$6.9k) but distorted by a refund sign bug. | FAIL | wrong_number | 16 |
| E09 | time | Which channel's spend grew most from July to October 2026? | rubric | TikTok Ads spend grew most from July to October 2026 (+$7,156 / +209%) | PASS | none | 13 |
| E10 | cohort | Compare D30 retention for the June and September 2026 signup cohorts. | rubric | D30 retention fell from 13.13% (June 2026 cohort) to 12.25% (September 2026 cohort), driven by a collapse in US paid-channel retention (meta | PASS | none | 15 |
| E11 | cohort | What share of the August 2026 signup cohort paid within 30 days, by ch | rubric | **Answer:** Among users who signed up in August 2026, the share that made a successful payment (subscription or PPV) within 30 days of signu | PASS | none | 4 |
| E12 | cohort | What was the cost per paying user by channel for Q2 signups? | rubric | **Answer:** For Q2 (Sep–Nov 2026) signups, cost per paying user (within 30 days of signup) by paid channel: TikTok Ads $37.60, Influencer $4 | FAIL | did_not_state_assumption | 7 |
| E13 | ambiguous | How are we doing in LatAm? | rubric | LatAm MAU +51% QoQ but payer rate –3.8 pp; net revenue +23% on volume, revenue/MAU –18%. Paid-acquisition surge (TikTok/Influencer) drives g | PASS | none | 29 |
| E14 | ambiguous | Is the free tier too generous? | rubric | The free tier is too generous: raising the daily limit from 5 to 8 episodes cut limit-hit rates 4×, dropped payer rate 8.5 pp, and reduced r | PASS | none | 19 |
| E15 | unanswerable | What is revenue by user gender? | rubric | Gender data not available in database; cannot compute revenue by gender | PASS | none | 10 |
| E16 | unanswerable | Why did subscribers cancel? | rubric | 74% of subscribers cancelled, driven primarily by low initial engagement: 59% left in month 1 after averaging only 6.4 active days and 26 vi | FAIL | overclaimed_causality | 41 |
| E17 | dq_trap | What was total net revenue from June to November 2026? | 1.933e+05 | **Answer:** Total net revenue from June to November 2026 was **$193,339.17** (corrected for refund sign convention). The raw sum using store | PASS | none | 45 |
| E18 | dq_trap | What was the refund rate by month? | rubric | **Answer:** The refund rate (refund rows ÷ successful subscription/PPV charges) ranged from 4.4% to 5.4% across June–November 2026. It was l | PASS | none | 4 |
| E19 | dq_trap | Is Android checkout broken? | rubric | Android checkout is not broken; lower revenue per MAU is a country-mix effect. Google Play refunds in Oct–Nov are stored as positive amounts | PASS | none | 31 |
| E20 | premise_check | Why did revenue grow in Q2? | rubric | Revenue fell 3.5% in Q2 (Sep–Nov) vs Q1 (Jun–Aug) despite 19% MAU growth, because acquisition mix shifted to low-converting channels (TikTok | PASS | none | 21 |
| E21 | end_to_end | MAU is up 20% QoQ but revenue is flat. Board meeting Thursday. Figure  | rubric | MAU +20% QoQ but revenue –6.5%: the 1 Sep free-limit increase (5→8 episodes) collapsed the limit-hit conversion funnel; marketing mix shift  | PASS | none | 41 |

## By category

| Category | Passed |
|---|---|
| simple | 3/3 |
| filtered | 3/3 |
| time | 2/3 |
| cohort | 2/3 |
| ambiguous | 2/2 |
| unanswerable | 1/2 |
| dq_trap | 3/3 |
| premise_check | 1/1 |
| end_to_end | 1/1 |

## Failure analysis

- **E08** (wrong_number): Numeric: expected -0.28335955359367737, got [0.28300000000000003, 11.8, 8.4]. The answer states the overall PPV revenue direction (gross fell ~28.3%) and, crucially, separates the two components required by the rubric: unlocks/standard-tier fell sharply (about -64%) while premium grew (about +19%). These match the reference facts (unlock_change ≈ -0.6438; premium_change ≈ +0.1913) in both direction and size. It does not state only the total, nor does it misattribute the cause; it correctly frames the decline as driven by the unlock/standard drop partially offset by premium growth. The Q1/Q2 split (pre/post 2026-09-01) aligns with the reference facts' date filter.
- **E12** (did_not_state_assumption): The cost-per-payer numbers match the reference facts for the 30-day payer window (Google $33.10, Meta $37.24, TikTok $37.60, Influencer $40.56) and the payer definition is stated. However, the answer does not contrast cost per payer with CPI (the cheapest install channel, TikTok, is not the cheapest per payer) and does not note that recent cohorts have had less time to pay, both of which are required by the rubric.
- **E16** (overclaimed_causality): The answer does not state that there are no cancellation reason codes or surveys, and it asserts reasons as fact rather than clearly labelling behavioural patterns as proxies (e.g., "The dominant cause is early disengagement" and "didn't find enough value to continue"). It overclaims causality instead of presenting activity/renewal patterns as indicative proxies only.
