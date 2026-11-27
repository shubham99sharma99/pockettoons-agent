"""Generate the synthetic PocketToons dataset into DuckDB (and optionally SQLite).

Run:  python data/generate_data.py            -> data/pockettoons.duckdb (schema raw)
      python data/generate_data.py --sqlite   -> also data/pockettoons.sqlite

How the story is built (all parameters live in data/config.py)
---------------------------------------------------------------
The simulation runs day by day from app launch (Dec 2025) to 30 Nov 2026 and
writes rows only for the 6-month window (1 Jun - 30 Nov 2026).

1. Acquisition. Each day, paid signups per channel = spend / CPI (Poisson),
   and each channel brings users from a fixed country mix. Organic/referral
   signups arrive at a steady rate. From 15 Aug the growth team ramps total
   spend +40 % and moves budget from Meta/Google (mostly US) to TikTok and
   influencers (mostly PH/ID/BR/MX). Prices stay flat at $9.99 everywhere.
2. Engagement. Each user is "engaged" or "casual" and has a daily churn hazard
   that is high in week 1 and then flattens. A live user opens the app with a
   fixed probability (weekends +15 %). Subscribers churn from the app slower.
3. Viewing. An active user wants 1 + NegBin episodes. 12 % of wanted episodes
   are premium. Subscribers watch everything as `sub`.
4. Paywall. A non-subscriber gets `free` standard episodes up to the daily free
   limit (5, raised to 8 on 1 Sep). Wanting more is a "paywall moment": the user
   subscribes, unlocks up to 3 episodes at $0.99 each (`ppv`), or stops. Stopping
   adds a frustration bump to tomorrow's churn hazard. Raising the limit
   therefore lowers paywall moments (fewer payers) and lifts retention (more MAU).
   Purchase probabilities depend on country only: never on platform, so any
   platform gap is a mix effect.
5. Premium episodes are never free: non-subscribers may buy them at $1.99.
6. Payments. Every charge attempt fails 6 % of the time; first purchases are
   retried by some users, renewals are retried once. 3.4 % of successful
   charges are refunded within 0-7 days. ~0.1 % of charges are double-posted.
7. Renewals every 30 days; 8 % of renewals are cancelled voluntarily, and users
   who stopped using the app cancel at their next renewal.
8. Data quality bug: from 1 Oct, Google Play refunds are written with a
   positive amount, against the documented negative-refund convention.
9. `users.subscription_*` is the final-state snapshot on 30 Nov.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent
DAY0 = pd.Timestamp(C.APP_LAUNCH)
N_DAYS = (pd.Timestamp(C.END) - DAY0).days + 1
WIN0 = (pd.Timestamp(C.START) - DAY0).days
LIMIT_DAY = (pd.Timestamp(C.FREE_LIMIT_CHANGE_DATE) - DAY0).days
SHIFT_DAY = (pd.Timestamp(C.SPEND_SHIFT_START) - DAY0).days
BUG_DAY = (pd.Timestamp(C.REFUND_SIGN_BUG_START) - DAY0).days
Q2_DAY = (pd.Timestamp(C.Q2[0]) - DAY0).days


def day_to_date(d: int) -> pd.Timestamp:
    return DAY0 + pd.Timedelta(days=int(d))


# --------------------------------------------------------------------------- #
# 1. Marketing spend and signups
# --------------------------------------------------------------------------- #
def spend_plan(rng: np.random.Generator) -> pd.DataFrame:
    """Daily spend per paid channel for every simulated day."""
    rows = []
    lo, hi = C.TIKTOK_INFLUENCER_SHARE
    for d in range(N_DAYS):
        ramp = np.clip((d - SHIFT_DAY) / C.SPEND_SHIFT_RAMP_DAYS, 0.0, 1.0)
        total = C.BASE_DAILY_SPEND * (1 + C.SPEND_TOTAL_LIFT * ramp)
        if d < WIN0:
            total *= C.PRE_WINDOW_SPEND_SCALE
        ti_share = lo + (hi - lo) * ramp
        weekday = day_to_date(d).day_of_week
        week_noise = 1.08 if weekday in (4, 5) else 0.97   # heavier Fri/Sat buys
        for ch in C.PAID_CHANNELS:
            pair_share = ti_share if ch in ("tiktok_ads", "influencer") else 1 - ti_share
            spend = total * pair_share * C.SPEND_SPLIT_WITHIN[ch] * week_noise
            spend *= rng.lognormal(0, 0.08)
            imps = int(spend / C.CPM[ch] * 1000 * rng.lognormal(0, 0.05))
            clicks = int(rng.binomial(imps, C.CTR[ch]))
            rows.append((d, ch, round(spend, 2), imps, clicks))
    return pd.DataFrame(rows, columns=["day", "channel", "spend_usd", "impressions", "clicks"])


@dataclass
class Users:
    signup_day: np.ndarray
    country: np.ndarray
    source: np.ndarray
    platform: np.ndarray
    engaged: np.ndarray
    n: int = field(init=False)

    def __post_init__(self):
        self.n = len(self.signup_day)


def make_users(rng: np.random.Generator, spend: pd.DataFrame) -> Users:
    sd, co, so = [], [], []
    spend_by_day = {k: g for k, g in spend.groupby("day")}
    countries = np.array(C.COUNTRIES)
    for d in range(N_DAYS):
        # paid
        for _, r in spend_by_day[d].iterrows():
            k = rng.poisson(r.spend_usd / C.CPI[r.channel])
            mix = C.CHANNEL_COUNTRY_MIX[r.channel]
            cs = rng.choice(countries, size=k, p=[mix[c] for c in C.COUNTRIES])
            sd += [d] * k
            co += list(cs)
            so += [r.channel] * k
        # organic + referral
        rate = C.ORGANIC_PER_DAY
        if d < WIN0:
            rate *= C.PRE_WINDOW_ORGANIC_SCALE
        if d >= Q2_DAY:
            rate *= 1 + C.ORGANIC_GROWTH_Q2
        if day_to_date(d).day_of_week >= 5:
            rate *= 1.1
        k = rng.poisson(rate)
        cs = rng.choice(countries, size=k, p=[C.ORGANIC_COUNTRY_MIX[c] for c in C.COUNTRIES])
        srcs = rng.choice(list(C.ORGANIC_SPLIT), size=k, p=list(C.ORGANIC_SPLIT.values()))
        sd += [d] * k
        co += list(cs)
        so += list(srcs)

    sd = np.array(sd)
    co = np.array(co)
    so = np.array(so)
    n = len(sd)
    android_p = np.array([C.ANDROID_SHARE[c] for c in co])
    u = rng.random(n)
    platform = np.where(u < android_p, "android",
                        np.where(rng.random(n) < C.IOS_SHARE_OF_REST, "ios", "web"))
    engaged = rng.random(n) < C.ENGAGED_SHARE
    return Users(sd, co, so, platform.astype(object), engaged)


# --------------------------------------------------------------------------- #
# 2. Content catalog
# --------------------------------------------------------------------------- #
def make_catalog(rng: np.random.Generator) -> pd.DataFrame:
    adjectives = ["Crimson", "Silent", "Eternal", "Neon", "Hidden", "Shattered", "Midnight",
                  "Golden", "Frozen", "Wandering", "Iron", "Celestial", "Lost", "Burning", "Paper"]
    nouns = ["Blade", "Academy", "Kingdom", "Moon", "Garden", "Protocol", "Spirit", "Café",
             "Dragon", "Circuit", "Festival", "Archive", "Harbor", "Comet", "Lantern"]
    titles, seen = [], set()
    while len(titles) < C.N_TITLES:
        t = f"{rng.choice(adjectives)} {rng.choice(nouns)}"
        if t in seen:
            t = f"{t} {rng.integers(2, 4)}"
        if t not in seen:
            seen.add(t)
            titles.append(t)
    # Steady release cadence from 6 months before launch to the end of the window
    first = pd.Timestamp("2025-06-01")
    span = (pd.Timestamp(C.END) - first).days
    release = sorted(first + pd.to_timedelta(rng.integers(0, span, C.N_TITLES), unit="D"))
    # A launch library: the first 40 titles were licensed before launch
    release = [min(r, DAY0 - pd.Timedelta(days=int(rng.integers(1, 120)))) if i < 40 else r
               for i, r in enumerate(release)]
    tier = np.where(rng.random(C.N_TITLES) < C.PREMIUM_SHARE_OF_RELEASES, "premium", "standard")
    eps = rng.integers(C.EPISODES_RANGE[0], C.EPISODES_RANGE[1] + 1, C.N_TITLES)
    ep_sec = rng.integers(C.EPISODE_SECONDS[0], C.EPISODE_SECONDS[1] + 1, C.N_TITLES)
    return pd.DataFrame({
        "content_id": [f"C{i:04d}" for i in range(1, C.N_TITLES + 1)],
        "title": titles,
        "genre": rng.choice(C.GENRES, C.N_TITLES),
        "total_episodes": eps,
        "release_date": pd.to_datetime(release).date,
        "content_tier": tier,
        "_episode_sec": ep_sec,
        "_release_day": [(pd.Timestamp(r) - DAY0).days for r in release],
    })


# --------------------------------------------------------------------------- #
# 3. Simulation
# --------------------------------------------------------------------------- #
class Ledger:
    """Collects transaction rows; only rows dated inside the window are kept."""

    def __init__(self, rng, users: Users):
        self.rng = rng
        self.users = users
        self.rows: list[tuple] = []

    def _ts(self, d: int, base_sec: int | None = None) -> pd.Timestamp:
        sec = int(self.rng.integers(6 * 3600, 24 * 3600 - 600)) if base_sec is None else base_sec
        return day_to_date(d) + pd.Timedelta(seconds=sec)

    def charge(self, uid: int, d: int, typ: str, amount: float, content_id: str | None,
               force_ok: bool = False) -> bool:
        """One charge attempt. Returns True if it succeeded."""
        method = C.PAYMENT_METHOD[self.users.platform[uid]]
        ok = force_ok or self.rng.random() >= C.CHARGE_FAILURE_RATE
        ts = self._ts(d)
        self.rows.append((uid, d, ts, typ, amount, method, "success" if ok else "failed", content_id))
        if ok:
            if self.rng.random() < C.DUPLICATE_CHARGE_RATE:   # gateway double-post
                ts2 = ts + pd.Timedelta(seconds=int(self.rng.integers(20, 240)))
                self.rows.append((uid, d, ts2, typ, amount, method, "success", content_id))
            if self.rng.random() < C.REFUND_RATE:
                rd = d + int(self.rng.integers(0, 8))
                if rd < N_DAYS:
                    sign = -1.0
                    if rd >= BUG_DAY and method == C.REFUND_SIGN_BUG_METHOD:
                        sign = 1.0                              # the logging bug
                    self.rows.append((uid, rd, self._ts(rd), "refund", sign * amount, method,
                                      "success", content_id))
        return ok


def simulate(rng: np.random.Generator, users: Users, catalog: pd.DataFrame):
    n = users.n
    is_us = users.country == "US"
    alive = np.zeros(n, bool)
    frustrated = np.zeros(n, bool)
    sub_active = np.zeros(n, bool)
    sub_next = np.full(n, -1)
    sub_start = np.full(n, -1)
    sub_end = np.full(n, -1)
    ever_sub = np.zeros(n, bool)

    hazard_floor = np.where(users.engaged, C.HAZARD_FLOOR["engaged"], C.HAZARD_FLOOR["casual"])
    p_active = np.where(users.engaged, C.P_ACTIVE_IF_ALIVE["engaged"], C.P_ACTIVE_IF_ALIVE["casual"])
    dem_mean = np.where(is_us, C.EPISODE_DEMAND["US"]["mean"], C.EPISODE_DEMAND["new_markets"]["mean"])
    dem_disp = np.where(is_us, C.EPISODE_DEMAND["US"]["dispersion"],
                        C.EPISODE_DEMAND["new_markets"]["dispersion"])
    p_sub_pw = np.where(is_us, C.P_SUBSCRIBE_AT_PAYWALL["US"], C.P_SUBSCRIBE_AT_PAYWALL["new_markets"])
    p_unl_pw = np.where(is_us, C.P_UNLOCK_AT_PAYWALL["US"], C.P_UNLOCK_AT_PAYWALL["new_markets"])
    p_buy_prem = np.where(is_us, C.P_BUY_PREMIUM_EPISODE["US"], C.P_BUY_PREMIUM_EPISODE["new_markets"])
    p_sub_prem = np.where(is_us, C.P_SUBSCRIBE_ON_PREMIUM["US"], C.P_SUBSCRIBE_ON_PREMIUM["new_markets"])

    ledger = Ledger(rng, users)
    cat_std = catalog[catalog.content_tier == "standard"].reset_index(drop=True)
    cat_prem = catalog[catalog.content_tier == "premium"].reset_index(drop=True)

    def pick_titles(cat: pd.DataFrame, d: int, k: int):
        avail = np.where(cat._release_day.values <= d)[0]
        ranks = np.arange(1, len(avail) + 1)
        # newer titles get a mild boost; popularity is Zipf over a fixed shuffled order
        w = 1.0 / ranks ** C.TITLE_POPULARITY_ZIPF
        w = w / w.sum()
        idx = avail[rng.choice(len(avail), size=k, p=w)]
        return idx

    sess_chunks, view_chunks = [], []

    def start_sub(uid: int, d: int) -> bool:
        ok = ledger.charge(uid, d, "subscription", C.PRICE_SUB, None)
        if not ok and rng.random() < C.INITIAL_RETRY_PROB:
            ok = ledger.charge(uid, d, "subscription", C.PRICE_SUB, None)
        if ok:
            sub_active[uid] = True
            ever_sub[uid] = True
            sub_start[uid] = d
            sub_end[uid] = -1
            sub_next[uid] = d + C.SUB_PERIOD_DAYS
        return ok

    for d in range(N_DAYS):
        date = day_to_date(d)
        in_window = d >= WIN0
        limit = C.FREE_LIMIT["before"] if d < LIMIT_DAY else C.FREE_LIMIT["after"]

        # --- renewals ---------------------------------------------------------
        for uid in np.where(sub_active & (sub_next == d))[0]:
            if (not alive[uid]) or rng.random() < C.MONTHLY_VOLUNTARY_CHURN:
                sub_active[uid] = False
                sub_end[uid] = d
                continue
            ok = ledger.charge(uid, d, "subscription", C.PRICE_SUB, None)
            if not ok and d + 1 < N_DAYS and rng.random() < C.RENEWAL_RETRY_SUCCESS:
                # the store retries the card the next day; ~75 % of retries recover
                ok = ledger.charge(uid, d + 1, "subscription", C.PRICE_SUB, None, force_ok=True)
            if ok:
                sub_next[uid] = d + C.SUB_PERIOD_DAYS
            else:
                sub_active[uid] = False
                sub_end[uid] = d + 1

        # --- who is around today ---------------------------------------------
        new = users.signup_day == d
        alive |= new
        weekend = 1 + C.WEEKEND_ACTIVITY_LIFT * (date.day_of_week >= 5)
        pa = p_active * weekend * np.where(sub_active, C.SUBSCRIBER_ACTIVITY_MULT, 1.0)
        active = alive & ((rng.random(n) < np.minimum(pa, 0.95)) | new)
        idx = np.where(active)[0]
        k = len(idx)

        # --- demand -------------------------------------------------------------
        m = dem_mean[idx] - 1
        r = dem_disp[idx]
        demand = 1 + rng.negative_binomial(r, r / (r + m))
        prem_want = rng.binomial(demand, C.PREMIUM_WANT_SHARE)
        std_want = demand - prem_want

        subd = sub_active[idx].copy()
        n_free = np.where(subd, 0, np.minimum(std_want, limit))
        excess = np.where(subd, 0, std_want - n_free)
        n_sub_std = np.where(subd, std_want, 0)
        n_unlock = np.zeros(k, int)
        frustrated_today = np.zeros(n, bool)

        # --- paywall moments -----------------------------------------------------
        pw = np.where(excess > 0)[0]
        u = rng.random(len(pw))
        for j, uu in zip(pw, u):
            uid = idx[j]
            if uu < p_sub_pw[uid]:
                if start_sub(uid, d):
                    n_sub_std[j] = excess[j]
                    continue
                frustrated_today[uid] = True
            elif uu < p_sub_pw[uid] + p_unl_pw[uid]:
                want = min(excess[j], C.MAX_UNLOCKS_PER_PAYWALL)
                got = 0
                for _ in range(want):
                    if ledger.charge(uid, d, "ppv", C.PRICE_UNLOCK, "__std__"):
                        got += 1
                n_unlock[j] = got
            else:
                frustrated_today[uid] = True

        # --- premium episodes ---------------------------------------------------
        n_sub_prem = np.where(sub_active[idx], prem_want, 0)
        n_buy_prem = np.zeros(k, int)
        pj = np.where((~sub_active[idx]) & (prem_want > 0))[0]
        for j in pj:
            uid = idx[j]
            if rng.random() < p_sub_prem[uid] * prem_want[j]:
                if start_sub(uid, d):
                    n_sub_prem[j] = prem_want[j]
                    continue
            buys = rng.binomial(prem_want[j], p_buy_prem[uid])
            got = sum(ledger.charge(uid, d, "ppv", C.PRICE_PREMIUM, "__prem__") for _ in range(buys))
            n_buy_prem[j] = got

        # --- write views & sessions -------------------------------------------
        if in_window and k:
            parts = []
            for counts, vtype, cat in ((n_free, "free", cat_std), (n_sub_std, "sub", cat_std),
                                       (n_unlock, "ppv", cat_std), (n_sub_prem, "sub", cat_prem),
                                       (n_buy_prem, "ppv", cat_prem)):
                tot = int(counts.sum())
                if tot == 0:
                    continue
                vu = np.repeat(idx, counts)
                t = pick_titles(cat, d, tot)
                parts.append(pd.DataFrame({
                    "uid": vu, "day": d, "view_type": vtype,
                    "content_id": cat.content_id.values[t],
                    "episode_number": (rng.random(tot) * cat.total_episodes.values[t]).astype(int) + 1,
                    "content_duration_sec": cat._episode_sec.values[t],
                }))
            views = pd.concat(parts, ignore_index=True)
            comp = rng.beta(*C.COMPLETION_BETA, len(views))
            views["watch_duration_sec"] = (comp * views.content_duration_sec).astype(int)
            view_chunks.append(views)

            watch = np.bincount(np.searchsorted(idx, views.uid.values),
                                weights=views.watch_duration_sec.values, minlength=k)
            dur = (watch + rng.integers(45, 420, k)).astype(int)
            broken = rng.random(k) < C.BROKEN_SESSION_RATE
            dur[broken] = 0
            sess_chunks.append(pd.DataFrame({"uid": idx, "day": d, "duration_sec": dur}))
            # a second short browse-only session on some days
            extra = rng.random(k) < 0.12
            if extra.any():
                sess_chunks.append(pd.DataFrame({"uid": idx[extra], "day": d,
                                                 "duration_sec": rng.integers(20, 240, extra.sum())}))

        frustrated = frustrated_today

        # --- churn at end of day --------------------------------------------------
        tenure = d - users.signup_day
        h = hazard_floor + C.HAZARD_EARLY * np.exp(-np.maximum(tenure, 0) / C.HAZARD_EARLY_DECAY_DAYS)
        h = np.where(sub_active, h * C.SUBSCRIBER_HAZARD_MULT, h)
        h = h + C.FRUSTRATION_CHURN_BUMP * frustrated
        die = alive & (rng.random(n) < h) & ~new
        alive &= ~die

    state = dict(sub_active=sub_active, sub_start=sub_start, sub_end=sub_end, ever_sub=ever_sub)
    return sess_chunks, view_chunks, ledger, state


# --------------------------------------------------------------------------- #
# 4. Assemble tables
# --------------------------------------------------------------------------- #
def assemble(rng, users: Users, catalog, spend, sess_chunks, view_chunks, ledger, state):
    uid_str = np.array([f"U{i + 1:06d}" for i in range(users.n)])

    def to_date(day_arr):
        return (DAY0 + pd.to_timedelta(np.asarray(day_arr), unit="D")).date

    status = np.where(state["sub_active"], "active", np.where(state["ever_sub"], "cancelled", "never"))
    users_df = pd.DataFrame({
        "user_id": uid_str,
        "signup_date": to_date(users.signup_day),
        "country": users.country,
        "acquisition_source": users.source,
        "subscription_status": status,
        "subscription_start": [day_to_date(s).date() if s >= 0 else None for s in state["sub_start"]],
        "subscription_end": [day_to_date(e).date() if (e >= 0 and not a) else None
                             for e, a in zip(state["sub_end"], state["sub_active"])],
    })

    sessions = pd.concat(sess_chunks, ignore_index=True)
    sessions = sessions.sample(frac=1, random_state=1).sort_values(["day"], kind="stable")
    sessions_df = pd.DataFrame({
        "session_id": [f"S{i:08d}" for i in range(1, len(sessions) + 1)],
        "user_id": uid_str[sessions.uid.values],
        "date": to_date(sessions.day.values),
        "duration_sec": sessions.duration_sec.values.astype(int),
        "platform": users.platform[sessions.uid.values],
    })

    views = pd.concat(view_chunks, ignore_index=True)
    views = views.sample(frac=1, random_state=2).sort_values(["day"], kind="stable")
    views_df = pd.DataFrame({
        "view_id": [f"V{i:09d}" for i in range(1, len(views) + 1)],
        "user_id": uid_str[views.uid.values],
        "content_id": views.content_id.values,
        "episode_number": views.episode_number.values,
        "date": to_date(views.day.values),
        "watch_duration_sec": views.watch_duration_sec.values,
        "content_duration_sec": views.content_duration_sec.values,
        "view_type": views.view_type.values,
    })

    tx = pd.DataFrame(ledger.rows, columns=["uid", "day", "ts", "type", "amount_usd",
                                            "payment_method", "status", "_content"])
    tx = tx[(tx.day >= WIN0) & (tx.day < N_DAYS)].sort_values("ts").reset_index(drop=True)
    tx_df = pd.DataFrame({
        "txn_id": [f"T{i:08d}" for i in range(1, len(tx) + 1)],
        "user_id": uid_str[tx.uid.values],
        "date": to_date(tx.day.values),
        "created_at": tx.ts.values,
        "type": tx.type.values,
        "amount_usd": tx.amount_usd.round(2).values,
        "payment_method": tx.payment_method.values,
        "status": tx.status.values,
    })

    sp = spend[spend.day >= WIN0]
    spend_df = pd.DataFrame({
        "date": to_date(sp.day.values), "channel": sp.channel.values,
        "spend_usd": sp.spend_usd.values, "impressions": sp.impressions.values,
        "clicks": sp.clicks.values,
    })

    catalog_df = catalog.drop(columns=["_episode_sec", "_release_day"])
    return {"users": users_df, "sessions": sessions_df, "content_views": views_df,
            "transactions": tx_df, "content_catalog": catalog_df, "marketing_spend": spend_df}


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


def write_duckdb(tables: dict, path: Path):
    import duckdb
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA raw")
    for name, df in tables.items():
        con.execute(f"CREATE TABLE raw.{name} ({DDL[name]})")
        con.register("_df", df)
        cols = ", ".join(df.columns)
        con.execute(f"INSERT INTO raw.{name} SELECT {cols} FROM _df")
        con.unregister("_df")
    con.close()


def write_sqlite(tables: dict, path: Path):
    import sqlite3
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for name, df in tables.items():
        out = df.copy()
        for c in out.columns:
            if out[c].dtype == object or "date" in c or c == "created_at":
                out[c] = out[c].astype("string")
        out.to_sql(name, con, index=False)
    con.commit()
    con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(DATA_DIR / "pockettoons.duckdb"))
    ap.add_argument("--sqlite", action="store_true", help="also write data/pockettoons.sqlite")
    args = ap.parse_args(argv)

    rng = np.random.default_rng(C.SEED)
    spend = spend_plan(rng)
    users = make_users(rng, spend)
    catalog = make_catalog(rng)
    print(f"users simulated: {users.n:,}")
    sess, views, ledger, state = simulate(rng, users, catalog)
    tables = assemble(rng, users, catalog, spend, sess, views, ledger, state)
    for k, v in tables.items():
        print(f"  {k:16s} {len(v):>10,} rows")
    write_duckdb(tables, Path(args.out))
    print(f"wrote {args.out}")
    if args.sqlite:
        p = Path(args.out).with_suffix(".sqlite")
        write_sqlite(tables, p)
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
