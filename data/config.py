"""Every planted effect in the synthetic PocketToons dataset, with its date and size.

This file is DEVELOPER-ONLY ground truth. Nothing in it is shown to the agent:
the agent's prompt, tools and semantic layer never import this module, and
`tests/test_no_leakage.py` fails the build if they reference it.

The generator (`generate_data.py`) builds the data from mechanics: users arrive
from channels, decide each day whether to open the app, demand episodes, hit the
free limit, and choose to pay or leave. The planted story emerges from those
mechanics; no metric is hard-coded to drop on a date.
"""
from __future__ import annotations

import os  # noqa: E402
SEED = int(os.environ.get("PT_SEED", 2026))  # chosen from a 4-seed sweep; see README

# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
APP_LAUNCH = "2025-12-01"      # simulation starts here; legacy users accrue from launch
START = "2026-06-01"           # first date written to the database
END = "2026-11-30"             # last date written to the database
Q1 = ("2026-06-01", "2026-08-31")
Q2 = ("2026-09-01", "2026-11-30")

COUNTRIES = ["US", "PH", "ID", "BR", "MX"]
NEW_MARKETS = ["PH", "ID", "BR", "MX"]

# --------------------------------------------------------------------------- #
# Acquisition (root cause 2: shift to cheap, low-paying markets)
# --------------------------------------------------------------------------- #
PAID_CHANNELS = ["meta_ads", "google_ads", "tiktok_ads", "influencer"]
BASE_DAILY_SPEND = 1000.0             # USD/day across paid channels before the shift
PRE_WINDOW_SPEND_SCALE = 0.90         # launch period (Dec-May) ran at lower spend
SPEND_SHIFT_START = "2026-08-15"      # growth team moves budget to TikTok + influencers
SPEND_SHIFT_RAMP_DAYS = 21            # ramp length
SPEND_TOTAL_LIFT = 0.0                # budget held flat: a pure reallocation to cheaper channels
TIKTOK_INFLUENCER_SHARE = (0.20, 0.60)  # share of spend before -> after
SPEND_SPLIT_WITHIN = {                # how each pair splits its budget
    "meta_ads": 0.55, "google_ads": 0.45,       # of the meta+google budget
    "tiktok_ads": 0.55, "influencer": 0.45,     # of the tiktok+influencer budget
}
CPI = {"meta_ads": 7.5, "google_ads": 6.5, "tiktok_ads": 3.7, "influencer": 4.3}
CTR = {"meta_ads": 0.012, "google_ads": 0.025, "tiktok_ads": 0.009, "influencer": 0.015}
CPM = {"meta_ads": 9.0, "google_ads": 12.0, "tiktok_ads": 3.0, "influencer": 5.0}
CHANNEL_COUNTRY_MIX = {
    "meta_ads":   {"US": .80, "PH": .05, "ID": .05, "BR": .05, "MX": .05},
    "google_ads": {"US": .75, "PH": .05, "ID": .05, "BR": .10, "MX": .05},
    "tiktok_ads": {"US": .20, "PH": .25, "ID": .20, "BR": .20, "MX": .15},
    "influencer": {"US": .20, "PH": .20, "ID": .20, "BR": .25, "MX": .15},
}
ORGANIC_PER_DAY = 92.0                 # organic + referral signups/day in the window
ORGANIC_GROWTH_Q2 = 0.03              # organic grows only ~3 % (no seasonality story)
PRE_WINDOW_ORGANIC_SCALE = 0.90
ORGANIC_SPLIT = {"organic": 0.72, "referral": 0.28}
ORGANIC_COUNTRY_MIX = {"US": .58, "PH": .11, "ID": .09, "BR": .12, "MX": .10}

ANDROID_SHARE = {"US": .38, "PH": .85, "ID": .88, "BR": .85, "MX": .80}
IOS_SHARE_OF_REST = 0.80              # remaining users: 80 % iOS, 20 % web
PAYMENT_METHOD = {"ios": "app_store", "android": "google_play", "web": "card"}

# --------------------------------------------------------------------------- #
# Engagement
# --------------------------------------------------------------------------- #
ENGAGED_SHARE = 0.22                  # long-lived "fans" vs casual samplers
HAZARD_FLOOR = {"engaged": 0.010, "casual": 0.085}   # daily churn hazard after week 1
HAZARD_EARLY = 0.16                   # extra early-life hazard ...
HAZARD_EARLY_DECAY_DAYS = 4.0         # ... decaying with this time constant
P_ACTIVE_IF_ALIVE = {"engaged": 0.42, "casual": 0.28}
SUBSCRIBER_HAZARD_MULT = 0.35         # paying users churn from the app more slowly
SUBSCRIBER_ACTIVITY_MULT = 1.35
WEEKEND_ACTIVITY_LIFT = 0.15

# Episodes wanted per active day = 1 + NegBin(mean - 1, dispersion).
# Mean demand is similar everywhere (3.4-3.6), but US viewers have a heavier
# tail (binge sessions). That is why an 8-episode limit covers almost all
# new-market viewing but still binds for some US binge days: the interaction.
EPISODE_DEMAND = {
    "US":          {"mean": 3.6, "dispersion": 1.1},
    "new_markets": {"mean": 3.4, "dispersion": 2.6},
}
PREMIUM_WANT_SHARE = 0.12             # share of episodes wanted that are premium titles

# --------------------------------------------------------------------------- #
# Root cause 1: free daily limit raised
# --------------------------------------------------------------------------- #
FREE_LIMIT_CHANGE_DATE = "2026-09-01"
FREE_LIMIT = {"before": 5, "after": 8}
# Paywall moment = a non-subscriber wants more standard episodes than the limit.
P_SUBSCRIBE_AT_PAYWALL = {"US": 0.200, "new_markets": 0.050}
P_UNLOCK_AT_PAYWALL = {"US": 0.330, "new_markets": 0.082}   # unlocks = min(excess, 3)
MAX_UNLOCKS_PER_PAYWALL = 3
FRUSTRATION_CHURN_BUMP = 0.180        # extra next-day hazard after an unpaid paywall hit

# Premium content (not affected by the limit)
PREMIUM_SHARE_OF_RELEASES = 0.15
P_BUY_PREMIUM_EPISODE = {"US": 0.095, "new_markets": 0.024}
P_SUBSCRIBE_ON_PREMIUM = {"US": 0.055, "new_markets": 0.013}

# --------------------------------------------------------------------------- #
# Prices: flat in every country (part of root cause 2)
# --------------------------------------------------------------------------- #
PRICE_SUB, PRICE_UNLOCK, PRICE_PREMIUM = 9.99, 0.99, 1.99
SUB_PERIOD_DAYS = 30

# --------------------------------------------------------------------------- #
# Payments: steady, no planted change
# --------------------------------------------------------------------------- #
MONTHLY_VOLUNTARY_CHURN = 0.08
CHARGE_FAILURE_RATE = 0.06            # every method, every month
RENEWAL_RETRY_SUCCESS = 0.75          # => ~1.5 % of renewals end involuntarily
INITIAL_RETRY_PROB = 0.55             # user retries a failed first purchase
REFUND_RATE = 0.050                   # of successful charges, refunded 0-7 days later
DUPLICATE_CHARGE_RATE = 0.001         # gateway double-posts (realistic noise, ~0.1 %)

# --------------------------------------------------------------------------- #
# Data quality issue: refund sign flip
# --------------------------------------------------------------------------- #
REFUND_SIGN_BUG_START = "2026-10-01"
REFUND_SIGN_BUG_METHOD = "google_play"  # these refunds are stored as +amount from this date

# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #
N_TITLES = 120
EPISODES_RANGE = (12, 48)
EPISODE_SECONDS = (1260, 1500)
COMPLETION_BETA = (6.0, 4.0)          # mean 0.60, steady over time (dead end D5)
TITLE_POPULARITY_ZIPF = 0.55
GENRES = ["action", "romance", "fantasy", "comedy", "isekai", "slice_of_life", "thriller", "sports"]

# --------------------------------------------------------------------------- #
# Small realistic noise (should be found and ruled out)
# --------------------------------------------------------------------------- #
BROKEN_SESSION_RATE = 0.0015          # zero-duration sessions

# --------------------------------------------------------------------------- #
# Dead ends (deliberately NO effect)
# --------------------------------------------------------------------------- #
# * Platform never enters a purchase probability: any Android payer-rate drop is mix.
# * Completion, release cadence and premium share are steady.
