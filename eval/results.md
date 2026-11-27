# Eval results

Run 2026-11-27T16:26:53+00:00 · provider `nim` · agent `nvidia/nemotron-3-ultra-550b-a55b` · judge `nvidia/nemotron-3.5-super-vl-120b-a12b`

**12 / 21 passed (57%).** Median latency 177.59 s, median tool calls 10, median tokens in/out 88312/3938.

> **Warning:** 3 result(s) failed on API or judge errors, not agent behaviour. Re-run them (`--ids ...`) before reading the pass rate.

| ID | Category | Question | Expected | Agent headline | Result | Failure type | Tools |
|---|---|---|---|---|---|---|---|
| E01 | simple | What was MAU in October 2026? | 1.506e+04 | **Answer:** MAU in October 2026 was **15,057** users. (Q1, Q2) | PASS | none | 4 |
| E02 | simple | How many subscribers were active on 30 Nov 2026? | 2,835 | **Answer:** 2,840 subscribers were active on 30 Nov 2026. (Q5) | PASS | none | 10 |
| E03 | simple | What was total PPV revenue in Q2? | 8,445 | **Answer:** Total PPV revenue in Q2 (Sep–Nov 2026) was **$8,445.45** (Q1). | PASS | none | 7 |
| E04 | filtered | How many US users started a subscription in September 2026? | 595 | **Answer:** 543 US users started their first-ever subscription in September 2026 (Q5). | FAIL | wrong_number | 10 |
| E05 | filtered | What share of sessions in Brazil were on Android in November 2026? | 0.8337 | **Answer:** 83.37% of sessions in Brazil were on Android in November 2026 (Q1). | PASS | none | 3 |
| E06 | filtered | Split Q2 PPV revenue into paywall unlocks and premium episodes. | 2,386 | Q2 PPV revenue: $8,445 total — 71.7% Premium Episodes ($1.99), 28.3% Paywall Unlocks ($0.99) | FAIL | wrong_number | 37 |
| E07 | time | How did MAU change from September to October 2026? | 0.04621 | **Answer:** MAU grew from 14,392 in September 2026 to 15,057 in October 2026, an increase of 665 users (+4.6%) (Q1). | PASS | none | 4 |
| E08 | time | How did PPV revenue change from Q1 to Q2? | -0.2834 | **Answer:** PPV gross revenue fell **28.3%** from **$11,785 in Q1 (Jun–Aug)** to **$8,445 in Q2 (Sep–Nov)**. Net of refunds, it fell **25.8% | FAIL | wrong_number | 7 |
| E09 | time | Which channel's spend grew most from July to October 2026? | rubric | TikTok Ads spend grew most from July to October 2026 (+$7,156 / +209%) | PASS | none | 13 |
| E10 | cohort | Compare D30 retention for the June and September 2026 signup cohorts. | rubric | D30 retention fell from 13.13% (June 2026 cohort) to 12.25% (September 2026 cohort), driven by a collapse in US paid-channel retention (meta | PASS | none | 15 |
| E11 | cohort | What share of the August 2026 signup cohort paid within 30 days, by ch | rubric | **Answer:** Among users who signed up in August 2026, the share that made a successful payment (subscription or PPV) within 30 days of signu | PASS | none | 4 |
| E12 | cohort | What was the cost per paying user by channel for Q2 signups? | rubric | **Answer:** For Q2 (Sep–Nov 2026) signups, cost per paying user (within 30 days of signup) by paid channel: TikTok Ads $37.60, Influencer $4 | FAIL | did_not_state_assumption | 7 |
| E13 | ambiguous | How are we doing in LatAm? | rubric | LatAm MAU +51% QoQ but payer rate –3.8 pp; net revenue +23% on volume, revenue/MAU –18%. Paid-acquisition surge (TikTok/Influencer) drives g | FAIL | judge_error | 29 |
| E14 | ambiguous | Is the free tier too generous? | rubric | The free tier is too generous: raising the daily limit from 5 to 8 episodes cut limit-hit rates 4×, dropped payer rate 8.5 pp, and reduced r | PASS | none | 19 |
| E15 | unanswerable | What is revenue by user gender? | rubric | Gender data not available in database; cannot compute revenue by gender | FAIL | judge_error | 10 |
| E16 | unanswerable | Why did subscribers cancel? | rubric | Now I have a comprehensive picture. Let me compile the findings. | FAIL | loop_or_timeout | 43 |
| E17 | dq_trap | What was total net revenue from June to November 2026? | 1.933e+05 |  | FAIL | loop_or_timeout | 46 |
| E18 | dq_trap | What was the refund rate by month? | rubric | **Answer:** The refund rate (refund rows ÷ successful subscription/PPV charges) ranged from 4.4% to 5.4% across June–November 2026. It was l | PASS | none | 4 |
| E19 | dq_trap | Is Android checkout broken? | rubric | Android checkout is not broken; lower revenue per MAU is a country-mix effect. Google Play refunds in Oct–Nov are stored as positive amounts | PASS | none | 31 |
| E20 | premise_check | Why did revenue grow in Q2? | rubric | Revenue fell 3.5% in Q2 (Sep–Nov) vs Q1 (Jun–Aug) despite 19% MAU growth, because acquisition mix shifted to low-converting channels (TikTok | PASS | none | 21 |
| E21 | end_to_end | MAU is up 20% QoQ but revenue is flat. Board meeting Thursday. Figure  | rubric |  | FAIL | api_error | 23 |

## By category

| Category | Passed |
|---|---|
| simple | 3/3 |
| filtered | 1/3 |
| time | 2/3 |
| cohort | 2/3 |
| ambiguous | 1/2 |
| unanswerable | 0/2 |
| dq_trap | 2/3 |
| premise_check | 1/1 |
| end_to_end | 0/1 |

## Failure analysis

- **E04** (wrong_number): The reference fact computed from the same database is 593 US users with a subscription start in September 2026 (new subscription starts, not renewals). The agent reports 543 using a narrower 'first-ever subscription' definition, which excludes returning users who started a new subscription in September. That count does not match the reference, and the agent's dismissal of the 593 snapshot figure is unsupported; the question asks for users who started a subscription in September 2026, not users whose first-ever subscription began then.
- **E06** (wrong_number): Numeric: expected 2385.899999999943, got [2.0, 8445.0, 0.7170000000000001]. Both parts are provided and the numbers match the reference facts: premium PPV revenue in Q2 is $6,059.55, matching reference_facts premium_ppv_revenue_q2 (6059.5499999996) exactly, and paywall unlocks at $0.99 are $2,385.90, for a total of $8,445.45. The price points ($0.99 standard unlock vs $1.99 premium episode) and the split method (grouping successful PPV transactions by amount_usd) are correct. Minor shortcoming: the answer never explicitly states that transactions has no content_id, though its amount_usd-based split implicitly handles that limitation; the rubric asked for that note explicitly.
- **E08** (wrong_number): Numeric: expected -0.28335955359367737, got [0.28300000000000003, 11785.0, 1.0]. The answer correctly states the total PPV revenue decline and, crucially, separates the two components: unlocks fell about 64% and premium purchases rose about 19%, matching the reference facts (-0.6438 and +0.1913) in both direction and size. It does not misattribute the cause, so it passes.
- **E12** (did_not_state_assumption): The cost-per-payer numbers are correct and match the 30-day payer window facts (TikTok $37.60, Influencer $40.56, Meta $37.24, Google $33.10), and the payer definition is stated (distinct Q2 signups with a successful subscription/PPV charge within 30 days of signup). However, the answer fails two required rubric elements: (1) it never contrasts cost per payer with CPI or notes that the cheapest install channels (TikTok $3.65, Influencer $4.20) are not the cheapest per payer (Google $33.10 is cheapest), and (2) it does not note that recent cohorts have had less time to pay. Because the rubric requires all of these, the answer does not pass.
- **E13** (judge_error): judge error: judge reply has no JSON object
- **E15** (judge_error): judge error: Expecting value: line 5 column 16 (char 74)
- **E16** (loop_or_timeout): The answer is a non-answer placeholder ('Now I have a comprehensive picture. Let me compile the findings.') that provides none of the rubric-required content: it does not state that there are no cancellation reason codes or surveys, offers no behavioural proxies labelled as proxies, and asserts nothing verifiable. It fails all pass conditions.
- **E17** (loop_or_timeout): Numeric: expected 193339.16999996008, got []. The agent answer is empty. It did not detect the positive-amount refund data-quality issue, did not report a corrected net revenue, and did not quantify the gap versus the as-stored sum of 196400.49.
- **E21** (api_error): 
