"""Build the synthetic PocketToons dataset (DuckDB, optionally SQLite).

Usage
-----
    python data/generate_data.py                 # -> data/pockettoons.duckdb (schema raw)
    python data/generate_data.py --sqlite        # also data/pockettoons.sqlite
    python data/generate_data.py --check         # also print the planted-story checks
    python data/generate_data.py --seed 7 --check --no-write   # try another seed

What it builds
--------------
Six tables for a webtoon app, 1 Jun - 30 Nov 2026 (two quarters):
users, sessions, content_views, transactions, content_catalog, marketing_spend.

Every parameter, date and effect size lives in data/config.py. The story is
produced by user-level mechanics, never by editing a metric on a date:

  acquisition  Paid signups per channel per day = Poisson(spend / CPI); each
               channel has a fixed country mix. Organic + referral arrive at a
               steady rate. From 15 Aug the budget (held flat) is reallocated
               from Meta/Google (US-heavy) to TikTok/influencers (PH/ID/BR/MX).
  engagement   Users are "engaged" or "casual". Daily churn hazard is high in
               week 1 and then flattens; a live user opens the app with a fixed
               probability (weekends higher). Subscribers churn more slowly.
  viewing      An active user wants 1 + NegBin episodes; some are premium.
               Subscribers watch everything as `sub`.
  paywall      A non-subscriber gets `free` standard episodes up to the daily
               free limit (5, raised to 8 on 1 Sep). Wanting more is a paywall
               moment: subscribe, unlock up to 3 episodes (`ppv`), or stop.
               Stopping raises tomorrow's churn hazard. A higher limit means
               fewer paywall moments (fewer payers) and better retention (MAU).
               Purchase propensity depends on country only, never on platform.
  premium      Premium episodes are never free: buy at $1.99 or subscribe.
  payments     Charges fail at a steady rate; first purchases are sometimes
               retried, renewals are retried by the store. A share of
               successful charges is refunded 0-7 days later, and the gateway
               occasionally double-posts a charge.
  renewals     Every 30 days; some cancel voluntarily, and users who left the
               app cancel at their next renewal.
  data bug     From 1 Oct, Google Play refunds are written with a positive
               amount, against the documented "refunds negative" convention.
  snapshot     users.subscription_* is the final state on 30 Nov.

The simulation starts at app launch (Dec 2025) so the window opens with a
realistic installed base; only rows dated inside the window are written.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DATA_DIR))
import config as C  # noqa: E402

DAY0 = pd.Timestamp(C.APP_LAUNCH)


def day_of(date: str) -> int:
    return (pd.Timestamp(date) - DAY0).days


N_DAYS = day_of(C.END) + 1
WIN0 = day_of(C.START)
LIMIT_DAY = day_of(C.FREE_LIMIT_CHANGE_DATE)
SHIFT_DAY = day_of(C.SPEND_SHIFT_START)
BUG_DAY = day_of(C.REFUND_SIGN_BUG_START)
Q2_DAY = day_of(C.Q2[0])
WEEKDAY0 = DAY0.day_of_week
COUNTRIES = np.array(C.COUNTRIES)
METHODS = np.array(["app_store", "google_play", "card"])           # index = platform code
PLATFORMS = np.array(["ios", "android", "web"])
assert [C.PAYMENT_METHOD[p] for p in PLATFORMS] == list(METHODS)


def weekday(d: int) -> int:
    return (WEEKDAY0 + d) % 7


def by_market(param: dict, is_us: np.ndarray) -> np.ndarray:
    return np.where(is_us, param["US"], param["new_markets"])


# --------------------------------------------------------------------------- #
# 1. Marketing spend
# --------------------------------------------------------------------------- #
def build_spend(rng: np.random.Generator) -> pd.DataFrame:
    lo, hi = C.TIKTOK_INFLUENCER_SHARE
    rows = []
    for d in range(N_DAYS):
        ramp = float(np.clip((d - SHIFT_DAY) / C.SPEND_SHIFT_RAMP_DAYS, 0, 1))
        total = C.BASE_DAILY_SPEND * (1 + C.SPEND_TOTAL_LIFT * ramp)
        total *= C.PRE_WINDOW_SPEND_SCALE if d < WIN0 else 1.0
        total *= 1.08 if weekday(d) in (4, 5) else 0.97          # heavier Fri/Sat buys
        share_ti = lo + (hi - lo) * ramp
        for ch in C.PAID_CHANNELS:
            pair = share_ti if ch in ("tiktok_ads", "influencer") else 1 - share_ti
            spend = total * pair * C.SPEND_SPLIT_WITHIN[ch] * rng.lognormal(0, 0.08)
            imps = int(spend / C.CPM[ch] * 1000 * rng.lognormal(0, 0.05))
            rows.append((d, ch, round(spend, 2), imps, int(rng.binomial(imps, C.CTR[ch]))))
    return pd.DataFrame(rows, columns=["day", "channel", "spend_usd", "impressions", "clicks"])


# --------------------------------------------------------------------------- #
# 2. Users
# --------------------------------------------------------------------------- #
def build_users(rng: np.random.Generator, spend: pd.DataFrame) -> pd.DataFrame:
    day, country, source = [], [], []

    def add(d: int, k: int, mix: dict, src):
        day.append(np.full(k, d))
        country.append(rng.choice(COUNTRIES, size=k, p=[mix[c] for c in C.COUNTRIES]))
        source.append(np.full(k, src, dtype=object) if isinstance(src, str) else src)

    for r in spend.itertuples(index=False):
        add(r.day, rng.poisson(r.spend_usd / C.CPI[r.channel]), C.CHANNEL_COUNTRY_MIX[r.channel], r.channel)
    for d in range(N_DAYS):
        rate = C.ORGANIC_PER_DAY
        rate *= C.PRE_WINDOW_ORGANIC_SCALE if d < WIN0 else 1.0
        rate *= 1 + C.ORGANIC_GROWTH_Q2 if d >= Q2_DAY else 1.0
        rate *= 1.1 if weekday(d) >= 5 else 1.0
        k = rng.poisson(rate)
        add(d, k, C.ORGANIC_COUNTRY_MIX,
            rng.choice(list(C.ORGANIC_SPLIT), size=k, p=list(C.ORGANIC_SPLIT.values())).astype(object))

    u = pd.DataFrame({"signup_day": np.concatenate(day), "country": np.concatenate(country),
                      "source": np.concatenate(source)})
    u = u.sort_values("signup_day", kind="stable").reset_index(drop=True)
    n = len(u)
    android = rng.random(n) < u.country.map(C.ANDROID_SHARE).values
    ios = rng.random(n) < C.IOS_SHARE_OF_REST
    u["platform_code"] = np.where(android, 1, np.where(ios, 0, 2))
    u["engaged"] = rng.random(n) < C.ENGAGED_SHARE
    return u


# --------------------------------------------------------------------------- #
# 3. Content catalog
# --------------------------------------------------------------------------- #
def build_catalog(rng: np.random.Generator) -> pd.DataFrame:
    adjectives = ["Crimson", "Silent", "Eternal", "Neon", "Hidden", "Shattered", "Midnight",
                  "Golden", "Frozen", "Wandering", "Iron", "Celestial", "Lost", "Burning", "Paper"]
    nouns = ["Blade", "Academy", "Kingdom", "Moon", "Garden", "Protocol", "Spirit", "Café",
             "Dragon", "Circuit", "Festival", "Archive", "Harbor", "Comet", "Lantern"]
    titles: list[str] = []
    while len(titles) < C.N_TITLES:
        t = f"{rng.choice(adjectives)} {rng.choice(nouns)}"
        t = t if t not in titles else f"{t} {len(titles) % 3 + 2}"
        if t not in titles:
            titles.append(t)
    first = pd.Timestamp("2025-06-01")
    release = np.sort(rng.integers(0, (pd.Timestamp(C.END) - first).days, C.N_TITLES))
    release_day = (first - DAY0).days + release
    # the first 40 titles are the licensed launch library
    release_day[:40] = np.minimum(release_day[:40], -rng.integers(1, 120, 40))
    return pd.DataFrame({
        "content_id": [f"C{i:04d}" for i in range(1, C.N_TITLES + 1)],
        "title": titles,
        "genre": rng.choice(C.GENRES, C.N_TITLES),
        "total_episodes": rng.integers(C.EPISODES_RANGE[0], C.EPISODES_RANGE[1] + 1, C.N_TITLES),
        "release_date": (DAY0 + pd.to_timedelta(release_day, unit="D")).date,
        "content_tier": np.where(rng.random(C.N_TITLES) < C.PREMIUM_SHARE_OF_RELEASES, "premium", "standard"),
        "_episode_sec": rng.integers(C.EPISODE_SECONDS[0], C.EPISODE_SECONDS[1] + 1, C.N_TITLES),
        "_release_day": release_day,
    })


# --------------------------------------------------------------------------- #
# 4. Payments ledger (vectorised)
# --------------------------------------------------------------------------- #
class Ledger:
    TYPES = np.array(["subscription", "ppv", "refund"])

    def __init__(self, rng: np.random.Generator, method_code: np.ndarray):
        self.rng = rng
        self.method = method_code
        self.chunks: list[tuple] = []          # (uid, day, sec, type, amount, method, ok)

    def _write(self, uid, day, sec, typ, amount, ok):
        self.chunks.append((uid, day, sec, np.full(len(uid), typ), amount, self.method[uid], ok))

    def charge(self, uid: np.ndarray, d: int, typ: int, price: float, force_ok=False) -> np.ndarray:
        """One charge attempt per element of `uid` on day d. Returns success mask."""
        uid = np.asarray(uid, dtype=np.int64)
        k = len(uid)
        if k == 0:
            return np.zeros(0, bool)
        rng = self.rng
        ok = np.ones(k, bool) if force_ok else rng.random(k) >= C.CHARGE_FAILURE_RATE
        sec = rng.integers(6 * 3600, 24 * 3600 - 600, k)
        amount = np.full(k, price)
        self._write(uid, np.full(k, d), sec, typ, amount, ok)
        # gateway double-post a few minutes later
        dup = ok & (rng.random(k) < C.DUPLICATE_CHARGE_RATE)
        if dup.any():
            self._write(uid[dup], np.full(dup.sum(), d), sec[dup] + rng.integers(20, 240, dup.sum()),
                        typ, amount[dup], np.ones(dup.sum(), bool))
        # refunds 0-7 days later; the logging bug flips the sign for Google Play from BUG_DAY
        ref = ok & (rng.random(k) < C.REFUND_RATE)
        if ref.any():
            ru = uid[ref]
            rd = d + rng.integers(0, 8, len(ru))
            keep = rd < N_DAYS
            ru, rd = ru[keep], rd[keep]
            bug = (rd >= BUG_DAY) & (METHODS[self.method[ru]] == C.REFUND_SIGN_BUG_METHOD)
            amt = np.where(bug, price, -price)
            self._write(ru, rd, rng.integers(6 * 3600, 24 * 3600 - 600, len(ru)), 2, amt,
                        np.ones(len(ru), bool))
        return ok

    def frame(self) -> pd.DataFrame:
        cols = [np.concatenate(x) for x in zip(*self.chunks)]
        df = pd.DataFrame(dict(zip(["uid", "day", "sec", "type", "amount", "method", "ok"], cols)))
        return df


# --------------------------------------------------------------------------- #
# 5. Day-by-day simulation
# --------------------------------------------------------------------------- #
def simulate(rng: np.random.Generator, users: pd.DataFrame, catalog: pd.DataFrame):
    n = len(users)
    signup = users.signup_day.values
    is_us = users.country.values == "US"
    engaged = users.engaged.values
    ledger = Ledger(rng, users.platform_code.values)

    hazard_floor = np.where(engaged, C.HAZARD_FLOOR["engaged"], C.HAZARD_FLOOR["casual"])
    p_active = np.where(engaged, C.P_ACTIVE_IF_ALIVE["engaged"], C.P_ACTIVE_IF_ALIVE["casual"])
    dem_mean = np.where(is_us, C.EPISODE_DEMAND["US"]["mean"], C.EPISODE_DEMAND["new_markets"]["mean"])
    dem_disp = np.where(is_us, C.EPISODE_DEMAND["US"]["dispersion"], C.EPISODE_DEMAND["new_markets"]["dispersion"])
    p_sub_pw = by_market(C.P_SUBSCRIBE_AT_PAYWALL, is_us)
    p_unl_pw = by_market(C.P_UNLOCK_AT_PAYWALL, is_us)
    p_buy_prem = by_market(C.P_BUY_PREMIUM_EPISODE, is_us)
    p_sub_prem = by_market(C.P_SUBSCRIBE_ON_PREMIUM, is_us)

    alive = np.zeros(n, bool)
    sub_active = np.zeros(n, bool)
    sub_next = np.full(n, -1)
    sub_start = np.full(n, -1)
    sub_end = np.full(n, -1)
    ever_sub = np.zeros(n, bool)

    cats = {t: catalog[catalog.content_tier == t].reset_index(drop=True) for t in ("standard", "premium")}
    zipf = {t: 1.0 / np.arange(1, len(c) + 1) ** C.TITLE_POPULARITY_ZIPF for t, c in cats.items()}
    sessions, views = [], []

    def start_sub(uid: np.ndarray, d: int) -> np.ndarray:
        ok = ledger.charge(uid, d, 0, C.PRICE_SUB)
        retry = ~ok & (rng.random(len(uid)) < C.INITIAL_RETRY_PROB)
        ok[retry] = ledger.charge(uid[retry], d, 0, C.PRICE_SUB)
        s = uid[ok]
        sub_active[s], ever_sub[s] = True, True
        sub_start[s], sub_end[s], sub_next[s] = d, -1, d + C.SUB_PERIOD_DAYS
        return ok

    for d in range(N_DAYS):
        limit = C.FREE_LIMIT["before"] if d < LIMIT_DAY else C.FREE_LIMIT["after"]

        # renewals ----------------------------------------------------------
        due = np.where(sub_active & (sub_next == d))[0]
        if len(due):
            cancel = ~alive[due] | (rng.random(len(due)) < C.MONTHLY_VOLUNTARY_CHURN)
            c = due[cancel]
            sub_active[c], sub_end[c] = False, d
            bill = due[~cancel]
            ok = ledger.charge(bill, d, 0, C.PRICE_SUB)
            retry = ~ok & (rng.random(len(bill)) < C.RENEWAL_RETRY_SUCCESS) & (d + 1 < N_DAYS)
            ledger.charge(bill[retry], d + 1, 0, C.PRICE_SUB, force_ok=True)
            ok |= retry
            sub_next[bill[ok]] = d + C.SUB_PERIOD_DAYS
            lost = bill[~ok]
            sub_active[lost], sub_end[lost] = False, d + 1

        # who opens the app -------------------------------------------------
        new = signup == d
        alive |= new
        pa = p_active * (1 + C.WEEKEND_ACTIVITY_LIFT * (weekday(d) >= 5))
        pa = np.where(sub_active, pa * C.SUBSCRIBER_ACTIVITY_MULT, pa)
        idx = np.where(alive & ((rng.random(n) < np.minimum(pa, 0.95)) | new))[0]
        k = len(idx)

        # demand ------------------------------------------------------------
        m, r = dem_mean[idx] - 1, dem_disp[idx]
        demand = 1 + rng.negative_binomial(r, r / (r + m))
        prem_want = rng.binomial(demand, C.PREMIUM_WANT_SHARE)
        std_want = demand - prem_want
        subd = sub_active[idx]
        n_free = np.where(subd, 0, np.minimum(std_want, limit))
        excess = np.where(subd, 0, std_want - n_free)
        n_sub_std = np.where(subd, std_want, 0)
        n_unlock = np.zeros(k, int)
        frustrated = np.zeros(n, bool)

        # paywall moments ---------------------------------------------------
        pw = np.where(excess > 0)[0]
        u = rng.random(len(pw))
        ps, pu = p_sub_pw[idx[pw]], p_unl_pw[idx[pw]]
        want_sub, want_unl = pw[u < ps], pw[(u >= ps) & (u < ps + pu)]
        frustrated[idx[pw[u >= ps + pu]]] = True
        ok = start_sub(idx[want_sub], d)
        n_sub_std[want_sub[ok]] = excess[want_sub[ok]]
        frustrated[idx[want_sub[~ok]]] = True
        tries = np.minimum(excess[want_unl], C.MAX_UNLOCKS_PER_PAYWALL)
        rep = np.repeat(want_unl, tries)
        got = ledger.charge(idx[rep], d, 1, C.PRICE_UNLOCK)
        np.add.at(n_unlock, rep[got], 1)

        # premium episodes ---------------------------------------------------
        n_sub_prem = np.where(sub_active[idx], prem_want, 0)
        n_buy_prem = np.zeros(k, int)
        pj = np.where(~sub_active[idx] & (prem_want > 0))[0]
        go_sub = pj[rng.random(len(pj)) < p_sub_prem[idx[pj]] * prem_want[pj]]
        ok = start_sub(idx[go_sub], d)
        n_sub_prem[go_sub[ok]] = prem_want[go_sub[ok]]
        buyers = np.setdiff1d(pj, go_sub[ok], assume_unique=True)
        buys = rng.binomial(prem_want[buyers], p_buy_prem[idx[buyers]])
        rep = np.repeat(buyers, buys)
        got = ledger.charge(idx[rep], d, 1, C.PRICE_PREMIUM)
        np.add.at(n_buy_prem, rep[got], 1)

        # rows for the window -------------------------------------------------
        if d >= WIN0 and k:
            parts = []
            for counts, vtype, tier in ((n_free, "free", "standard"), (n_sub_std, "sub", "standard"),
                                        (n_unlock, "ppv", "standard"), (n_sub_prem, "sub", "premium"),
                                        (n_buy_prem, "ppv", "premium")):
                tot = int(counts.sum())
                if not tot:
                    continue
                cat = cats[tier]
                avail = np.where(cat._release_day.values <= d)[0]
                w = zipf[tier][: len(avail)]
                t = avail[rng.choice(len(avail), size=tot, p=w / w.sum())]
                parts.append(pd.DataFrame({
                    "uid": np.repeat(idx, counts), "day": d, "view_type": vtype,
                    "content_id": cat.content_id.values[t],
                    "episode_number": (rng.random(tot) * cat.total_episodes.values[t]).astype(int) + 1,
                    "content_duration_sec": cat._episode_sec.values[t],
                }))
            v = pd.concat(parts, ignore_index=True)
            v["watch_duration_sec"] = (rng.beta(*C.COMPLETION_BETA, len(v)) * v.content_duration_sec).astype(int)
            views.append(v)
            watch = np.bincount(np.searchsorted(idx, v.uid.values), weights=v.watch_duration_sec.values, minlength=k)
            dur = (watch + rng.integers(45, 420, k)).astype(int)
            dur[rng.random(k) < C.BROKEN_SESSION_RATE] = 0             # broken sessions (noise)
            sessions.append(pd.DataFrame({"uid": idx, "day": d, "duration_sec": dur}))
            extra = rng.random(k) < 0.12                                # short browse-only session
            if extra.any():
                sessions.append(pd.DataFrame({"uid": idx[extra], "day": d,
                                              "duration_sec": rng.integers(20, 240, extra.sum())}))

        # churn at end of day -------------------------------------------------
        tenure = np.maximum(d - signup, 0)
        h = hazard_floor + C.HAZARD_EARLY * np.exp(-tenure / C.HAZARD_EARLY_DECAY_DAYS)
        h = np.where(sub_active, h * C.SUBSCRIBER_HAZARD_MULT, h) + C.FRUSTRATION_CHURN_BUMP * frustrated
        alive &= ~(alive & ~new & (rng.random(n) < h))

    state = dict(sub_active=sub_active, sub_start=sub_start, sub_end=sub_end, ever_sub=ever_sub)
    return sessions, views, ledger, state


# --------------------------------------------------------------------------- #
# 6. Assemble the six tables
# --------------------------------------------------------------------------- #
def to_date(days) -> np.ndarray:
    return (DAY0 + pd.to_timedelta(np.asarray(days), unit="D")).date


def assemble(users, catalog, spend, sessions, views, ledger, state) -> dict[str, pd.DataFrame]:
    uid = np.array([f"U{i + 1:06d}" for i in range(len(users))])
    platform = PLATFORMS[users.platform_code.values]
    act, ever = state["sub_active"], state["ever_sub"]
    users_df = pd.DataFrame({
        "user_id": uid,
        "signup_date": to_date(users.signup_day.values),
        "country": users.country.values,
        "acquisition_source": users.source.values,
        "subscription_status": np.where(act, "active", np.where(ever, "cancelled", "never")),
        "subscription_start": [to_date([s])[0] if s >= 0 else None for s in state["sub_start"]],
        "subscription_end": [to_date([e])[0] if e >= 0 and not a else None
                             for e, a in zip(state["sub_end"], act)],
    })

    s = pd.concat(sessions, ignore_index=True).sample(frac=1, random_state=1).sort_values("day", kind="stable")
    sessions_df = pd.DataFrame({
        "session_id": [f"S{i:08d}" for i in range(1, len(s) + 1)],
        "user_id": uid[s.uid.values], "date": to_date(s.day.values),
        "duration_sec": s.duration_sec.values.astype(int), "platform": platform[s.uid.values],
    })

    v = pd.concat(views, ignore_index=True).sample(frac=1, random_state=2).sort_values("day", kind="stable")
    views_df = pd.DataFrame({
        "view_id": [f"V{i:09d}" for i in range(1, len(v) + 1)],
        "user_id": uid[v.uid.values], "content_id": v.content_id.values,
        "episode_number": v.episode_number.values, "date": to_date(v.day.values),
        "watch_duration_sec": v.watch_duration_sec.values,
        "content_duration_sec": v.content_duration_sec.values, "view_type": v.view_type.values,
    })

    t = ledger.frame()
    t = t[(t.day >= WIN0) & (t.day < N_DAYS)]
    t["ts"] = DAY0 + pd.to_timedelta(t.day * 86400 + t.sec, unit="s")
    t = t.sort_values("ts", kind="stable").reset_index(drop=True)
    tx_df = pd.DataFrame({
        "txn_id": [f"T{i:08d}" for i in range(1, len(t) + 1)],
        "user_id": uid[t.uid.values], "date": to_date(t.day.values),
        "created_at": t.ts.values, "type": Ledger.TYPES[t.type.values.astype(int)],
        "amount_usd": t.amount.round(2).values, "payment_method": METHODS[t.method.values],
        "status": np.where(t.ok.values.astype(bool), "success", "failed"),
    })

    sp = spend[spend.day >= WIN0]
    spend_df = pd.DataFrame({"date": to_date(sp.day.values), "channel": sp.channel.values,
                             "spend_usd": sp.spend_usd.values, "impressions": sp.impressions.values,
                             "clicks": sp.clicks.values})
    return {"users": users_df, "sessions": sessions_df, "content_views": views_df, "transactions": tx_df,
            "content_catalog": catalog.drop(columns=["_episode_sec", "_release_day"]),
            "marketing_spend": spend_df}


# --------------------------------------------------------------------------- #
# 7. Writers
# --------------------------------------------------------------------------- #
DDL = {
    "users": """user_id VARCHAR PRIMARY KEY, signup_date DATE, country VARCHAR,
        acquisition_source VARCHAR, subscription_status VARCHAR,
        subscription_start DATE, subscription_end DATE""",
    "sessions": """session_id VARCHAR PRIMARY KEY, user_id VARCHAR, date DATE,
        duration_sec INTEGER, platform VARCHAR""",
    "content_views": """view_id VARCHAR PRIMARY KEY, user_id VARCHAR, content_id VARCHAR,
        episode_number INTEGER, date DATE, watch_duration_sec INTEGER,
        content_duration_sec INTEGER, view_type VARCHAR""",
    "transactions": """txn_id VARCHAR PRIMARY KEY, user_id VARCHAR, date DATE,
        created_at TIMESTAMP, type VARCHAR, amount_usd DOUBLE, payment_method VARCHAR,
        status VARCHAR""",
    "content_catalog": """content_id VARCHAR PRIMARY KEY, title VARCHAR, genre VARCHAR,
        total_episodes INTEGER, release_date DATE, content_tier VARCHAR""",
    "marketing_spend": """date DATE, channel VARCHAR, spend_usd DOUBLE, impressions BIGINT,
        clicks BIGINT""",
}


def write_duckdb(tables: dict, path: Path) -> None:
    import duckdb
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA raw")
    for name, df in tables.items():
        con.execute(f"CREATE TABLE raw.{name} ({DDL[name]})")
        con.register("_df", df)
        con.execute(f"INSERT INTO raw.{name} SELECT {', '.join(df.columns)} FROM _df")
        con.unregister("_df")
    con.close()


def write_sqlite(tables: dict, path: Path) -> None:
    import sqlite3
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    for name, df in tables.items():
        out = df.copy()
        for c in out.columns:
            if out[c].dtype == object or "date" in c or c == "created_at":
                out[c] = out[c].astype("string")
        out.to_sql(name, con, index=False)
    con.commit()
    con.close()


# --------------------------------------------------------------------------- #
# 8. Story check (developer-only: prints what the analyst should find)
# --------------------------------------------------------------------------- #
def story_check(t: dict[str, pd.DataFrame]) -> dict[str, float]:
    s, tx, ms, u = t["sessions"], t["transactions"], t["marketing_spend"], t["users"]
    q2 = pd.Timestamp(C.Q2[0]).date()
    month = pd.to_datetime(s.date).dt.to_period("M")
    mau = s.groupby(month).user_id.nunique()
    ok = tx[tx.status == "success"]
    tq2 = ok.date >= q2
    true_amt = np.where(ok.type == "refund", -ok.amount_usd.abs(), ok.amount_usd)
    rev_m = ok.groupby(pd.to_datetime(ok.date).dt.to_period("M")).amount_usd.sum()
    bug = ok[(ok.type == "refund") & (ok.amount_usd > 0)]
    bug_q2_share = 2 * bug.amount_usd.sum() / ok[tq2].amount_usd.sum()
    ti = ms.channel.isin(["tiktok_ads", "influencer"])
    early, late = ms.date < pd.Timestamp("2026-08-01").date(), ms.date >= pd.Timestamp("2026-09-15").date()
    new_q = u[u.signup_date >= pd.Timestamp(C.Q1[0]).date()]
    us_share = new_q.groupby(new_q.signup_date >= q2).country.apply(lambda c: (c == "US").mean())
    out = {
        "mau_growth_qoq": mau[mau.index >= pd.Period(C.Q2[0], "M")].mean() / mau[mau.index < pd.Period(C.Q2[0], "M")].mean() - 1,
        "revenue_stored_qoq": ok[tq2].amount_usd.sum() / ok[~tq2].amount_usd.sum() - 1,
        "revenue_true_qoq": true_amt[tq2.values].sum() / true_amt[~tq2.values].sum() - 1,
        "refund_bug_rows": len(bug),
        "refund_bug_share_of_q2_revenue": bug_q2_share,
        "tiktok_influencer_share_before": ms[ti & early].spend_usd.sum() / ms[early].spend_usd.sum(),
        "tiktok_influencer_share_after": ms[ti & late].spend_usd.sum() / ms[late].spend_usd.sum(),
        "us_share_of_signups_q1": us_share.get(False, np.nan),
        "us_share_of_signups_q2": us_share.get(True, np.nan),
        "avg_monthly_revenue": rev_m.mean(),
        "avg_monthly_spend": ms.groupby(pd.to_datetime(ms.date).dt.to_period("M")).spend_usd.sum().mean(),
    }
    print("\nMAU by month:\n" + mau.to_string())
    print("\nRevenue as stored by month:\n" + rev_m.round(0).to_string())
    print("\nStory check:")
    for k, v in out.items():
        print(f"  {k:34s} {v:,.3f}" if isinstance(v, float) else f"  {k:34s} {v:,}")
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(DATA_DIR / "pockettoons.duckdb"))
    ap.add_argument("--sqlite", action="store_true", help="also write a SQLite copy next to --out")
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--check", action="store_true", help="print the planted-story checks")
    ap.add_argument("--no-write", action="store_true", help="simulate only (for seed sweeps)")
    args = ap.parse_args(argv)

    t0 = time.time()
    rng = np.random.default_rng(args.seed)
    spend = build_spend(rng)
    users = build_users(rng, spend)
    catalog = build_catalog(rng)
    print(f"seed {args.seed}: simulating {len(users):,} users over {N_DAYS} days ...")
    sessions, views, ledger, state = simulate(rng, users, catalog)
    tables = assemble(users, catalog, spend, sessions, views, ledger, state)
    for k, v in tables.items():
        print(f"  {k:16s} {len(v):>11,} rows")
    print(f"simulated in {time.time() - t0:.0f}s")
    checks = story_check(tables) if args.check else {}
    if not args.no_write:
        write_duckdb(tables, Path(args.out))
        print(f"wrote {args.out}")
        if args.sqlite:
            p = Path(args.out).with_suffix(".sqlite")
            write_sqlite(tables, p)
            print(f"wrote {p}")
    return checks


if __name__ == "__main__":
    main()
