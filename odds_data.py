"""
odds_data.py
Pulls game lines and player prop odds from The Odds API
(https://the-odds-api.com). Requires a free (or paid) API key.

Free tier: 500 requests/month. Each call below can cost more than 1
"request unit" depending on how many markets/regions you request, so
be mindful during testing.
"""
import requests

BASE = "https://api.the-odds-api.com/v4"

GAME_MARKETS = "h2h,spreads,totals"

# Player prop markets available for MLB on The Odds API (subject to
# sportsbook coverage; not everything is offered by every book, and
# market key names can change — check https://the-odds-api.com/sports-odds-data/betting-markets.html
# if any of these come back empty).
PLAYER_PROP_MARKETS = [
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
    "batter_rbis",
    "batter_walks",
    "batter_stolen_bases",
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
    "pitcher_outs",
]


def get_events(api_key: str):
    """List upcoming MLB events (needed to query per-event player props)."""
    url = f"{BASE}/sports/baseball_mlb/events"
    resp = requests.get(url, params={"apiKey": api_key}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_game_odds(api_key: str, regions: str = "us"):
    """Moneyline / run line / totals for all upcoming MLB games."""
    url = f"{BASE}/sports/baseball_mlb/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": GAME_MARKETS,
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_player_props(api_key: str, event_id: str, regions: str = "us"):
    """
    Player prop odds for a single event. Must be called per-event
    (The Odds API does not support bulk player props across all games
    in one call).
    """
    url = f"{BASE}/sports/baseball_mlb/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": ",".join(PLAYER_PROP_MARKETS),
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()
