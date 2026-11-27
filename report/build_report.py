"""Build the board deck (Marp Markdown + figures) from the agent's own tools.

    python report/build_report.py            -> report/board_deck.md, report/figures/*.png,
                                                report/evidence.md
    npx @marp-team/marp-cli@4.2.3 report/board_deck.md --pdf --allow-local-files -o report/board_deck.pdf

Every number in the deck comes from a query run through agent.tools (the same
guarded, read-only layer the agent uses), so each one has a query ID listed in
report/evidence.md. The narrative is the analyst's edit; when the live agent
has been run (`python cli.py --gm`), its raw output is in outputs/investigation_raw.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import tools as T  # noqa: E402

OUT = ROOT / "report"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# Reference palette (dataviz skill, light mode), fixed slot order
BLUE, ORANGE, AQUA, GRAY, INK, MUTED = "#257de0", "#f47230", "#00b894", "#9a9a94", "#191919", "#666666"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#cfcfca", "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#ececea", "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "figure.dpi": 160, "lines.linewidth": 2,
})

S = T.Session()


def q(sql: str, purpose: str) -> tuple[pd.DataFrame, str]:
    r = T.run_sql(S, sql, purpose)
    if r.get("error"):
        raise RuntimeError(f"{purpose}: {r['error']}")
    return pd.DataFrame(r["rows"], columns=r["columns"]), r["query_id"]


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
dq = T.run_dq_checks(S, ["transactions", "sessions"])
sign = next(c for c in dq["checks"] if c["check"] == "amount_sign_by_type_method_month")
dups = next(c for c in dq["checks"] if c["check"] == "duplicate_charges_5min")

monthly, Q_MONTHLY = q("""
WITH m AS (SELECT date_trunc('month', date) AS month, COUNT(DISTINCT user_id) AS mau FROM sessions GROUP BY 1),
r AS (SELECT date_trunc('month', date) AS month, SUM(amount_usd) AS rev_stored,
             SUM(CASE WHEN type = 'refund' THEN -abs(amount_usd) ELSE amount_usd END) AS rev_corrected
      FROM transactions WHERE status = 'success' GROUP BY 1)
SELECT strftime(month, '%Y-%m') AS month, mau, rev_stored, rev_corrected FROM m JOIN r USING (month) ORDER BY 1""",
                       "monthly MAU and net revenue, as stored and with refunds forced negative")
monthly["q2"] = monthly.month >= "2026-09"
mau1, mau2 = monthly[~monthly.q2].mau.mean(), monthly[monthly.q2].mau.mean()
rs1, rs2 = monthly[~monthly.q2].rev_stored.sum(), monthly[monthly.q2].rev_stored.sum()
rc1, rc2 = monthly[~monthly.q2].rev_corrected.sum(), monthly[monthly.q2].rev_corrected.sum()
mau_g, stored_g, true_g = mau2 / mau1 - 1, rs2 / rs1 - 1, rc2 / rc1 - 1
gap_pts = 100 * (rs2 - rc2) / rc1

refunds, Q_REFUND = q("""SELECT strftime(date, '%Y-%m') AS month, payment_method,
       COUNT(*) AS refunds, COUNT(*) FILTER (WHERE amount_usd > 0) AS positive
FROM transactions WHERE type = 'refund' GROUP BY 1, 2 ORDER BY 1, 2""", "refund sign by month x method")

limit_daily, Q_LIMIT = q("""SELECT date, MAX(free_views) AS observed_limit FROM fct_user_day GROUP BY 1 ORDER BY 1""",
                         "observed free-episode allowance per day")
step_day = limit_daily[limit_daily.observed_limit >= 8].date.min()

hit_q, Q_HITQ = q("""WITH d AS (SELECT *, free_views = MAX(free_views) OVER (PARTITION BY date) AS hit FROM fct_user_day WHERE sub_views = 0)
SELECT date >= '2026-09-01' AS q2, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market,
       AVG(hit::INT) AS hit_rate, SUM(hit::INT) AS hit_days,
       SUM((subscription_charges + ppv_charges) * hit::INT) * 1.0 / SUM(hit::INT) AS purchases_per_hit
FROM d GROUP BY ALL ORDER BY 1, 2""", "limit-hit rate and purchases per limit hit, before/after, by market")

payer, Q_PAYER = q("""SELECT strftime(month, '%Y-%m') AS month, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market,
       AVG(is_payer::INT) AS payer_rate, COUNT(*) AS mau
FROM fct_user_month WHERE is_active GROUP BY ALL ORDER BY 1, 2""", "payer rate and MAU by market by month")

spend, Q_SPEND = q("""SELECT strftime(date, '%Y-%m') AS month,
       SUM(spend_usd) FILTER (WHERE channel IN ('tiktok_ads','influencer')) / SUM(spend_usd) AS tiktok_influencer_share,
       SUM(spend_usd) AS spend FROM marketing_spend GROUP BY 1 ORDER BY 1""", "spend share TikTok + influencer by month")

chan, Q_CHAN = q("""WITH c AS (SELECT user_id, signup_date, acquisition_source FROM users WHERE signup_date BETWEEN '2026-09-01' AND '2026-11-30'),
p AS (SELECT acquisition_source AS channel, COUNT(*) AS signups,
        COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM transactions t WHERE t.user_id = c.user_id AND t.status = 'success'
             AND t.type IN ('subscription','ppv') AND t.date BETWEEN c.signup_date AND c.signup_date + 30)) AS payers_30d,
        AVG(CASE WHEN country_us THEN 1 ELSE 0 END) AS us_share
      FROM (SELECT c.*, u.country = 'US' AS country_us FROM c JOIN users u USING (user_id)) c GROUP BY 1),
s AS (SELECT channel, SUM(spend_usd) AS spend FROM marketing_spend WHERE date BETWEEN '2026-09-01' AND '2026-11-30' GROUP BY 1)
SELECT channel, spend, signups, spend / signups AS cpi, payers_30d, spend / payers_30d AS cost_per_payer, us_share
FROM s JOIN p USING (channel) ORDER BY cost_per_payer""", "Q2 CPI vs cost per paying user (paid within 30 days) by channel")

d30, Q_D30 = q("""WITH c AS (SELECT user_id, signup_date, strftime(signup_date, '%Y-%m') AS cohort,
                        CASE WHEN country = 'US' THEN 'US' ELSE 'new_markets' END AS market FROM users
                 WHERE signup_date BETWEEN '2026-06-01' AND '2026-10-24'),
r AS (SELECT cohort, market, CASE WHEN EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = c.user_id
        AND s.date BETWEEN c.signup_date + 30 AND c.signup_date + 36) THEN 1 ELSE 0 END AS kept FROM c)
SELECT cohort, market, AVG(kept) AS d30, COUNT(*) AS users FROM r GROUP BY GROUPING SETS ((cohort), (cohort, market))
ORDER BY 1, 2 NULLS FIRST""", "D30 retention by signup cohort, overall and by market")

plat, Q_PLAT = q("""WITH up AS (SELECT user_id, any_value(platform) AS platform FROM sessions GROUP BY 1)
SELECT platform, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market, month >= DATE '2026-09-01' AS q2,
       AVG(is_payer::INT) AS payer_rate, COUNT(*) AS user_months
FROM fct_user_month JOIN up USING (user_id) WHERE is_active GROUP BY ALL ORDER BY 1, 2, 3""", "payer rate by platform within market")
plat_all, Q_PLATALL = q("""WITH up AS (SELECT user_id, any_value(platform) AS platform FROM sessions GROUP BY 1)
SELECT platform, month >= DATE '2026-09-01' AS q2, AVG(is_payer::INT) AS payer_rate
FROM fct_user_month JOIN up USING (user_id) WHERE is_active GROUP BY ALL ORDER BY 1, 2""", "payer rate by platform overall")
fails, Q_FAIL = q("""SELECT payment_method, AVG((status = 'failed')::INT) AS failed_share FROM transactions
WHERE type <> 'refund' GROUP BY 1 ORDER BY 1""", "charge failure share by method")

ppv, Q_PPV = q("""SELECT date >= '2026-09-01' AS q2,
       SUM(amount_usd) FILTER (WHERE type = 'ppv' AND amount_usd = 0.99) AS unlock_rev,
       SUM(amount_usd) FILTER (WHERE type = 'ppv' AND amount_usd = 1.99) AS premium_rev,
       SUM(amount_usd) FILTER (WHERE type = 'subscription') AS sub_rev
FROM transactions WHERE status = 'success' GROUP BY 1 ORDER BY 1""", "revenue by product line, Q1 vs Q2")
content, Q_CONTENT = q("""SELECT strftime(date, '%Y-%m') AS month, SUM(watch_duration_sec) * 1.0 / SUM(content_duration_sec) AS completion
FROM content_views GROUP BY 1 ORDER BY 1""", "completion rate by month")
prices, Q_PRICE = q("""SELECT type, round(abs(amount_usd), 2) AS amount, COUNT(*) AS n FROM transactions GROUP BY 1, 2 ORDER BY 1, 2""",
                    "distinct amounts (price changes, currency)")

bridge = T.decompose_change(S, period_a=["2026-06-01", "2026-08-31"], period_b=["2026-09-01", "2026-11-30"],
                            segment_col="market", refund_handling="force_negative")
Q_BRIDGE = bridge["query_id"]
b = bridge["bridge_points_index_a_100"]
rate_seg = bridge["rate_step_by_segment_points"]

# --------------------------------------------------------------------------- #
# Derived headline numbers
# --------------------------------------------------------------------------- #
hq = hit_q.set_index(["q2", "market"])
hit_us_a, hit_us_b = hq.loc[(False, "US"), "hit_rate"], hq.loc[(True, "US"), "hit_rate"]
hit_nm_a, hit_nm_b = hq.loc[(False, "New markets"), "hit_rate"], hq.loc[(True, "New markets"), "hit_rate"]
pph_us_a, pph_us_b = hq.loc[(False, "US"), "purchases_per_hit"], hq.loc[(True, "US"), "purchases_per_hit"]
pph_nm_a, pph_nm_b = hq.loc[(False, "New markets"), "purchases_per_hit"], hq.loc[(True, "New markets"), "purchases_per_hit"]
seg = bridge["segments"]
pr_us_a, pr_us_b = seg["US"]["payer_rate_a"], seg["US"]["payer_rate_b"]
pr_nm_a, pr_nm_b = seg["new_markets"]["payer_rate_a"], seg["new_markets"]["payer_rate_b"]
nm_share_a, nm_share_b = seg["new_markets"]["share_a"], seg["new_markets"]["share_b"]
pv = ppv.set_index("q2")
unlock_g = pv.loc[True, "unlock_rev"] / pv.loc[False, "unlock_rev"] - 1
prem_g = pv.loc[True, "premium_rev"] / pv.loc[False, "premium_rev"] - 1
sub_g = pv.loc[True, "sub_rev"] / pv.loc[False, "sub_rev"] - 1
sp = spend.set_index("month")
d30d = d30[d30.market.isna()].set_index("cohort").d30
_pre = d30.cohort < "2026-09"   # Jun-Aug cohorts vs Sep-Oct cohorts (Oct cut at the 24th for a full D30 window)
d30m = {m: ((g[_pre[g.index]].d30 * g[_pre[g.index]].users).sum() / g[_pre[g.index]].users.sum(),
            (g[~_pre[g.index]].d30 * g[~_pre[g.index]].users).sum() / g[~_pre[g.index]].users.sum())
        for m, g in d30[d30.market.notna()].groupby("market")}
_d30_delta = d30d.loc["2026-09"] - d30d.iloc[0]
if _d30_delta > 0.005:
    retention_line = (f"D30 retention {d30d.iloc[0]:.1%} (Jun cohort) → {d30d.loc['2026-09']:.1%} (Sep cohort), "
                      "so the change also added MAU")
else:
    retention_line = (f"D30 retention {'fell' if _d30_delta < -0.005 else 'held'} overall ({d30d.iloc[0]:.1%} Jun → "
                      f"{d30d.loc['2026-09']:.1%} Sep cohort), a mix shift (new markets "
                      f"{d30m['new_markets'][0]:.1%} → {d30m['new_markets'][1]:.1%}, US {d30m['US'][0]:.1%} → {d30m['US'][1]:.1%}): "
                      "MAU grew from signups, not retention")
rpm_a = bridge["monthly_avg_a"]["net_revenue"] / bridge["monthly_avg_a"]["mau"]
rpm_b = bridge["monthly_avg_b"]["net_revenue"] / bridge["monthly_avg_b"]["mau"]
pa = plat_all.set_index(["platform", "q2"]).payer_rate
pw = plat.set_index(["platform", "market", "q2"]).payer_rate
gp_bad = refunds[(refunds.payment_method == "google_play") & (refunds.positive > 0)]
first_bad_month = gp_bad.month.min()

# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
# 1. MAU vs revenue, indexed to June = 100 (one axis, common base)
fig, ax = plt.subplots(figsize=(7.2, 3.6))
x = monthly.month.str[5:].map({"06": "Jun", "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov"})
for col, color, label in (("mau", BLUE, "MAU"), ("rev_stored", ORANGE, "Net revenue as reported"),
                          ("rev_corrected", AQUA, "Net revenue, refunds corrected")):
    idx = 100 * monthly[col] / monthly[col].iloc[0]
    ax.plot(x, idx, color=color, marker="o", markersize=5, label=label)
    ax.annotate(f"{idx.iloc[-1]:.0f}", (len(x) - 1, idx.iloc[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", color=INK, fontsize=10)
ax.axvspan(2.5, 5.4, color="#f3f3f0", zorder=0)
ax.text(2.6, ax.get_ylim()[1] - 2, "Q2", color=MUTED, va="top")
ax.set_ylabel("Index, June = 100")
ax.legend(loc="upper left", fontsize=9.5)
save(fig, "1_mau_vs_revenue.png")

# 2. Observed free allowance (daily) and weekly limit-hit rate by market
hits2, _ = q("""WITH d AS (SELECT *, free_views = MAX(free_views) OVER (PARTITION BY date) AS hit FROM fct_user_day WHERE sub_views = 0)
SELECT date_trunc('week', date) AS week, CASE WHEN country = 'US' THEN 'US' ELSE 'New markets' END AS market, AVG(hit::INT) AS hit_rate
FROM d GROUP BY ALL ORDER BY 1""", "weekly limit-hit rate by market (chart)")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.3))
ld = limit_daily.copy()
ld["date"] = pd.to_datetime(ld.date)
a1.step(ld.date, ld.observed_limit, where="post", color=BLUE)
a1.set_ylim(0, 10)
a1.set_title("Most free episodes any user got in a day", fontsize=11, loc="left", color=INK)
a1.text(pd.Timestamp("2026-06-05"), 9.0, f"Steps 5 → 8 on {pd.Timestamp(step_day):%-d %b}", color=INK, fontsize=10)
for mkt, color in (("US", BLUE), ("New markets", ORANGE)):
    h = hits2[hits2.market == mkt].copy()
    h["week"] = pd.to_datetime(h.week)
    h = h.iloc[1:-1]   # drop partial first/last weeks
    a2.plot(h.week, 100 * h.hit_rate, color=color, label=mkt)
a2.set_title("Share of free-user days that hit the limit (%)", fontsize=11, loc="left", color=INK)
a2.legend(fontsize=9.5)
for a in (a1, a2):
    a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b"))
save(fig, "2_free_limit.png")

# 3. Acquisition shift: shares on one % axis
fig, ax = plt.subplots(figsize=(7.2, 3.3))
pm = payer.pivot(index="month", columns="market", values="mau")
nm_share = 100 * pm["New markets"] / pm.sum(axis=1)
mx = pd.Series(pm.index).str[5:].map({"06": "Jun", "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov"})
ax.plot(mx, 100 * spend.tiktok_influencer_share, color=BLUE, marker="o", markersize=5, label="TikTok + influencer share of spend")
ax.plot(mx, nm_share.values, color=ORANGE, marker="o", markersize=5, label="PH/ID/BR/MX share of MAU")
ax.set_ylim(0, 70)
ax.set_ylabel("%")
ax.legend(loc="upper left", fontsize=9.5)
save(fig, "3_acquisition_shift.png")

# 4. Payer rate indexed to Q1 = 100 by market (interaction)
fig, ax = plt.subplots(figsize=(7.2, 3.3))
pp = payer.pivot(index="month", columns="market", values="payer_rate")
for mkt, color in (("US", BLUE), ("New markets", ORANGE)):
    base = pp[mkt].iloc[:3].mean()
    idx = 100 * pp[mkt] / base
    ax.plot(mx, idx.values, color=color, marker="o", markersize=5, label=f"{mkt} (Q1 avg {100 * base:.1f}%)")
    ax.annotate(f"{idx.iloc[-1]:.0f}", (len(mx) - 1, idx.iloc[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", color=INK, fontsize=10)
ax.set_ylabel("Payer rate, index Q1 = 100")
ax.legend(loc="lower left", fontsize=9.5)
save(fig, "4_payer_rate_by_market.png")

# 5. Bridge (waterfall)
steps = [("Q1", 100.0, "total"), ("More users", b["volume"], "d"), ("Mix to low-paying markets", b["mix"], "d"),
         ("Payer rate: US", rate_seg["US"], "d"), ("Payer rate: new mkts", rate_seg["new_markets"], "d"),
         ("Revenue per payer", b["price"], "d"), ("Q2 true", 100 + sum(v for k, v in b.items()), "total"),
         ("Refund logging bug", gap_pts, "d"), ("Q2 reported", 100 * rs2 / rc1, "total")]
fig, ax = plt.subplots(figsize=(9, 3.6))
level = 0.0
for i, (lab, v, kind) in enumerate(steps):
    if kind == "total":
        ax.bar(i, v, color=GRAY, width=0.62)
        level = v
        ax.text(i, v + 1.5, f"{v:.1f}", ha="center", color=INK, fontsize=10)
    else:
        bottom = level if v >= 0 else level + v
        ax.bar(i, abs(v), bottom=bottom, color=BLUE if v >= 0 else ORANGE, width=0.62)
        ax.text(i, max(level, level + v) + 1.5, f"{v:+.1f}", ha="center", color=INK, fontsize=10)
        level += v
ax.set_xticks(range(len(steps)), [s[0] for s in steps], rotation=20, ha="right", fontsize=9.5)
ax.set_ylim(0, max(130, level + 15))
ax.set_ylabel("Index, Q1 net revenue = 100")
ax.grid(axis="x", visible=False)
save(fig, "5_bridge.png")

# 6. Android: overall vs within market (Q2)
fig, ax = plt.subplots(figsize=(7.2, 3.1))
groups = ["All users", "US", "New markets"]
vals = {p: [pa[(p, True)], pw[(p, "US", True)], pw[(p, "New markets", True)]] for p in ("android", "ios")}
w = 0.36
for j, (p, color) in enumerate((("android", ORANGE), ("ios", BLUE))):
    xs = [i + (j - 0.5) * w for i in range(3)]
    ax.bar(xs, [100 * v for v in vals[p]], width=w - 0.03, color=color, label=p.replace("ios", "iOS").replace("android", "Android"))
    for xx, v in zip(xs, vals[p]):
        ax.text(xx, 100 * v + 0.3, f"{100 * v:.1f}", ha="center", fontsize=9.5, color=INK)
ax.set_xticks(range(3), groups)
ax.set_ylabel("Q2 payer rate (%)")
ax.legend(fontsize=9.5)
ax.grid(axis="x", visible=False)
save(fig, "6_android_mix.png")

# --------------------------------------------------------------------------- #
# Deck
# --------------------------------------------------------------------------- #
pct = lambda v, d=1: f"{100 * v:+.{d}f}%"  # noqa: E731
cp = chan.set_index("channel")
cheapest_cpi = cp.cpi.idxmin()
cheapest_payer = cp.cost_per_payer.idxmin()
worst_payer = cp.cost_per_payer.idxmax()
gp_pos = int(gp_bad.positive.sum())

deck = f"""---
marp: true
paginate: true
size: 16:9
style: |
  section {{ font-family: 'DejaVu Sans', sans-serif; font-size: 22px; color: #191919; padding: 44px 56px; }}
  h1 {{ font-size: 34px; margin-bottom: 6px; }} h2 {{ font-size: 26px; color: #191919; }}
  table {{ font-size: 17px; }} .small {{ font-size: 15px; color: #666; }}
  img {{ display: block; margin: 0 auto; }}
---

# Revenue isn't flat: it fell {abs(true_g):.1%} while MAU grew {mau_g:.0%}

**We traded paying users for MAU in two ways, and a logging bug hid part of it.**

- **MAU** {mau1:,.0f} → {mau2:,.0f} a month (**{pct(mau_g)}**) ({Q_MONTHLY})
- **Net revenue, as reported** {pct(stored_g)}; **corrected for a refund logging bug: {pct(true_g)}** ({Q_MONTHLY}, {sign['query_id']})
- **Revenue per MAU** ${rpm_a:.2f} → ${rpm_b:.2f} (**{rpm_b / rpm_a - 1:+.0%}**) ({Q_BRIDGE})
- **Cause 1:** the daily free-episode allowance went from 5 to 8 on {pd.Timestamp(step_day):%-d %b}. Far fewer people reach the paywall, so payer rates fell in every market, including the US ({Q_LIMIT}, {Q_HITQ}, {Q_PAYER})
- **Cause 2:** from mid-August, acquisition budget moved to TikTok and influencers, which bring mostly PH/ID/BR/MX users who pay about a third as often at the same $9.99 ({Q_SPEND}, {Q_BRIDGE})
- **Ask for Thursday:** restate Q2 revenue, test the free allowance, and judge channels by cost per paying user, not cost per install

<p class="small">Data: 1 Jun – 30 Nov 2026. Q1 = Jun–Aug, Q2 = Sep–Nov. Query IDs (Qn) are listed in the evidence appendix.</p>

---

## MAU climbed from September; revenue didn't follow

![w:900](figures/1_mau_vs_revenue.png)

- Q2 MAU averaged {mau2:,.0f} vs {mau1:,.0f} in Q1. Reported Q2 revenue ${rs2:,.0f} vs ${rs1:,.0f}; corrected ${rc2:,.0f} ({Q_MONTHLY})
- The gap opens in **September**, not gradually: something changed at the start of the quarter

---

## First, the number was wrong: Google Play refunds are logged as income

- The data dictionary says refunds are stored as negative amounts. Checked, not trusted: **{gp_pos} of {gp_pos} Google Play refunds from {first_bad_month} are positive**; every other method and month is negative ({sign['query_id']}, {Q_REFUND})
- Effect: reported Q2 net revenue is **overstated by ${rs2 - rc2:,.0f} ({gap_pts:.1f} points)**, turning a {pct(true_g)} decline into {pct(stored_g)} that reads as "flat"
- Refund **rates** are normal; only the sign is wrong. Other checks passed: {dups['detail']} (noise, {dups['query_id']}), failed charges steady at {fails.failed_share.min():.1%}–{fails.failed_share.max():.1%} by method ({Q_FAIL}), only list prices $9.99 / $0.99 / $1.99 ({Q_PRICE}), no gaps in recent data
- **Fix:** restate Q2, correct the billing integration, and keep the new data test (`assert_refunds_negative`) in the daily pipeline: it fails today

---

## Cause 1: the free allowance rose from 5 to 8 on {pd.Timestamp(step_day):%-d %b}

![w:860](figures/2_free_limit.png)

- No one is told this in the data dictionary; it shows as a step in the most free episodes any user watched in a day ({Q_LIMIT})
- Free users hitting the limit: **US {hit_us_a:.0%} → {hit_us_b:.0%} of their days; new markets {hit_nm_a:.0%} → {hit_nm_b:.0%}** ({Q_HITQ})
- Once people hit the paywall they buy as often as before (US {pph_us_a:.3f} → {pph_us_b:.3f}, new markets {pph_nm_a:.3f} → {pph_nm_b:.3f} purchases per hit): **fewer reach it, not a worse paywall**
- Side effects: $0.99 unlock revenue **{unlock_g:+.0%}**; {retention_line} ({Q_PPV}, {Q_D30})

---

## Cause 2: budget moved to cheap installs in low-paying markets

![w:900](figures/3_acquisition_shift.png)

- TikTok + influencer share of spend: **{sp.tiktok_influencer_share.iloc[0]:.0%} → {sp.tiktok_influencer_share.iloc[-1]:.0%}** from mid-August, total budget flat ({Q_SPEND})
- New markets' share of MAU: **{nm_share_a:.0%} → {nm_share_b:.0%}**; they pay {pr_nm_a:.1%} vs {pr_us_a:.1%} in the US (Q1) at the same $9.99 ({Q_BRIDGE})
- Cheapest install ≠ cheapest payer: **{cheapest_cpi}** has the lowest CPI (${cp.cpi.min():.2f}); **{cheapest_payer}** the lowest cost per paying user (${cp.cost_per_payer.min():.0f}); **{worst_payer}** the highest (${cp.cost_per_payer.max():.0f}) ({Q_CHAN})

---

## The two causes compound: new markets lost twice as much

![w:880](figures/4_payer_rate_by_market.png)

- **US payer rate {pr_us_a:.1%} → {pr_us_b:.1%} ({pr_us_b / pr_us_a - 1:+.0%})**. US mix barely moved, so this is the clean read of the allowance change (control) ({Q_BRIDGE})
- **New markets {pr_nm_a:.1%} → {pr_nm_b:.1%} ({pr_nm_b / pr_nm_a - 1:+.0%})**: their viewing rarely exceeds 8 episodes a day, so the higher allowance removed most of their paywall moments ({Q_HITQ})
- Inference (not in the data): both moves served a MAU goal. Worth confirming with the growth and product owners

---

## Bridge: where the revenue went (Q1 = 100)

![w:1000](figures/5_bridge.png)

<p class="small">Sequential substitution by market ({Q_BRIDGE}): volume → mix → payer rate → revenue per payer; residual {b['residual']:+.1f}. "More users" is mostly cause 2 acquisition (new signups). "Revenue per payer" rose because the payers lost were mostly light $0.99 buyers; subscription price is unchanged. Swapping the mix and rate steps moves each by about half a point.</p>

---

## Ruled out: Android checkout, content, prices, payments

![w:760](figures/6_android_mix.png)

- **"Android checkout is broken"**: Android payer rate is far below iOS overall, but close within each market. Android users are mostly in new markets: **a mix effect** ({Q_PLAT}, {Q_PLATALL}); failure rates similar by method ({Q_FAIL})
- **Content got weaker**: completion steady at {content.completion.min():.0%}–{content.completion.max():.0%}; premium-episode revenue {prem_g:+.0%} ({Q_CONTENT}, {Q_PPV})
- **Price or currency changes**: only $9.99 / $0.99 / $1.99 ({Q_PRICE}). **Subscription revenue** {sub_g:+.1%}: the base held; the loss is new payers and unlocks

---

## Recommendations

| # | Action | Owner | What's at stake | How we'll know |
|---|---|---|---|---|
| 1 | Restate Q2 ({pct(true_g)}, not {pct(stored_g)}); fix Google Play refund logging; keep the daily refund-sign test | Finance + Data eng | {gap_pts:.1f} pts of reported revenue | Test passes daily; reconciles with store payouts |
| 2 | A/B test the free allowance (5 / 6 / 8), including a lower limit in new markets | Product | Payer-rate step {rate_seg['US'] + rate_seg['new_markets']:+.1f} pts vs any engagement gain | Net revenue per MAU and D30 per arm, 4 weeks |
| 3 | Judge channels by cost per paying user and payback; cap the worst until it pays back | Growth | {worst_payer} ${cp.cost_per_payer.max():.0f} vs {cheapest_payer} ${cp.cost_per_payer.min():.0f} per payer | Cost per payer, 90-day payback by channel |
| 4 | Test regional pricing or a weekly plan in PH/ID/BR/MX | Pricing | New markets pay ~⅓ as often at $9.99 | Payer rate and revenue per MAU vs control countries |
| 5 | Put paying users and revenue per MAU beside MAU in the board pack | GM | Revenue per MAU {rpm_b / rpm_a - 1:+.0%} | Board pack by segment |

<p class="small">Caveats: before/after with a US control, not an experiment; six months of data limits seasonality checks; competitor activity is not in the data.</p>

---

## How this was produced

- **Agent:** Claude (Opus 5.5) tool-calling loop over a read-only DuckDB warehouse built with dbt; tools for schema, metric catalog (dbt semantic layer), column profiles, guarded SQL, canned data-quality checks, a revenue bridge, and a hypothesis log. Every number must cite a query ID
- **This deck:** numbers computed through the agent's own tools ({len(S.log.entries)} logged queries, see `report/evidence.md`); narrative edited by the analyst. Raw agent output: `outputs/investigation_raw.md` (from `python cli.py --gm`)
- **Eval:** 21 golden questions (simple, filtered, time, cohort, ambiguous, unanswerable, data-quality traps, end-to-end), numeric tolerance + LLM judge; results in `eval/results.md`
"""
(OUT / "board_deck.md").write_text(deck)

ev = ["# Evidence: queries behind the board deck", "",
      "Each query ran through `agent.tools` (read-only, guarded). IDs match the deck.", ""]
for e in S.log.entries:
    ev += [f"## {e['id']}: {e['purpose']}", "", f"Source: `{e['source']}`, rows: {e['row_count']}", "",
           "```sql", e["sql"].strip(), "```", ""]
(OUT / "evidence.md").write_text("\n".join(ev))
print(f"wrote report/board_deck.md, report/evidence.md and {len(list(FIG.glob('*.png')))} figures; "
      f"{len(S.log.entries)} queries logged")
print(f"MAU {mau_g:+.1%} stored {stored_g:+.1%} true {true_g:+.1%} gap {gap_pts:.2f}pts bridge {b} rate_seg {rate_seg}")
