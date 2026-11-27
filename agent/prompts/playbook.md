# Investigation playbook (generic)

Use this for open-ended "why did X move?" questions. For simple lookups, skip it.

## 1. Build a MECE issue tree from an identity

For a growth-vs-monetisation gap, start from the revenue identity:

    Net revenue = MAU x sum_s( share_s x payer_rate_s x ARPPU_s ) - leakage

Branches:
- A. Measurement: is the number right? (always first)
- B. User volume: where did the extra users come from?
- C. User mix: who are they (country, channel, platform, tenure)?
- D. Payer conversion: why does a different share pay?
- E. Revenue per payer: do payers pay more or less?
- F. Leakage: do we keep what we bill (refunds, failures, churn)?

For other questions (retention, a spike, a crash) build the tree from that
metric's own identity (e.g. MAU = new + retained + reactivated).

## 2. Generic hypothesis checklist (growth-vs-monetisation)

A. Measurement
- A1 MAU definition or counting changed: recompute monthly distinct users from sessions
- A2 Duplicate user records: users sharing signup date, country and source; activity per new user
- A3 Bots / fake installs: share of new users with one session under 15 s, by source
- A4 Internal or test accounts: missing country, test-style IDs, extreme activity
- A5 Recent data incomplete: daily row counts per table up to the last date
- A6 Failed or pending charges counted: revenue by status
- A7 Duplicate charge rows: same user, type and amount within 5 minutes
- A8 Local currency stored as USD: distinct amount_usd values by country
- A9 Revenue timing: plan amounts; charge dates vs subscription_start
- A10 Sign conventions: sign of amount_usd by type x payment_method x month
- A11 Broken session records: zero/negative durations; sessions before signup
- A12 Subscriber status vs payments: users.subscription_status vs latest successful charge

B. User volume
- B1 More new users (by source)
- B2 Better retention keeps more users active (cohort retention before/after any dated change)
- B3 Reactivation of lapsed users
- B4 Seasonality (weekly shape, organic signups)
- B5 A hit title drove growth (top title share of views)
- B6 Country misattributed (check whether the schema can even test it)

C. User mix
- C1 Country mix moved toward lower-paying segments
- C2 Spend moved between channels (CPI vs cost per payer)
- C3 New users are lighter viewers
- C4 Older users left and were replaced

D. Payer conversion
- D1 Paywall exposure changed (how often users reach the free allowance)
- D2 Paywall converts differently once reached
- D3 A platform's checkout broke (check overall AND within each country)
- D4 Payment declines rose (failed share by method x month)
- D5 Content got weaker (releases, completion, premium purchases)
- D6 External factor (competitor): not in data; look for gradual vs sudden change
- D7 Trials/promotions (zero or discounted charges)
- D8 Users watched less
- D9 Less premium content

E. Revenue per payer
- E1 Subscription price/discounts changed (distinct amounts by month)
- E2 PPV prices changed
- E3 Fewer PPV purchases per buyer (split unlock vs premium)
- E4 Big spenders left (revenue share of top 5 % of payers)

F. Leakage
- F1 Voluntary churn
- F2 Failed renewals
- F3 Refund rate (count based)
- F4 Chargebacks / reversals not typed as refunds
- F5 Store fees or taxes (charge amounts vs list prices)

You do not have to test every item: rank by expected size x likelihood x ease,
test the top ones, and say which you skipped.

## 3. Isolation techniques

- Mix vs behaviour: if an aggregate rate moves but is flat within every segment, it is mix (Simpson's paradox).
- Dated change: look for a step on a specific date (daily series); compare fixed windows before/after.
- Control segment: a segment whose mix did not change isolates behaviour changes.
- Interaction: difference-in-differences: (change in segment X) - (change in control).
- Funnel: exposure (reached paywall) -> intent (attempted payment) -> success. Find the stage that moved.

## 4. Quantify

Use decompose_change for a volume / mix / rate / price bridge. Every point of
change should be attributed to one cause; if more than ~1 point is unexplained,
go back to the tree.
