"""
mlb_data.py
Pulls schedule, probable pitchers, and recent player performance
from the free, public MLB Stats API (no API key required).
Docs (unofficial but well-known): https://statsapi.mlb.com/api/v1
"""
import requests
from datetime import date, timedelta

BASE = "https://statsapi.mlb.com/api/v1"


def get_schedule(target_date: str = None):
    """Return list of games for a given date (YYYY-MM-DD), default = today."""
    if target_date is None:
        target_date = date.today().isoformat()

    url = f"{BASE}/schedule"
    params = {
        "sportId": 1,
        "date": target_date,
        "hydrate": "probablePitcher,team,linescore",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            away = g["teams"]["away"]
            home = g["teams"]["home"]
            games.append({
                "game_pk": g["gamePk"],
                "game_date": g["gameDate"],
                "status": g["status"]["detailedState"],
                "away_team": away["team"]["name"],
                "away_team_id": away["team"]["id"],
                "home_team": home["team"]["name"],
                "home_team_id": home["team"]["id"],
                "away_pitcher": away.get("probablePitcher", {}).get("fullName"),
                "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
                "home_pitcher": home.get("probablePitcher", {}).get("fullName"),
                "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
            })
    return games


def get_team_roster(team_id: int, roster_type: str = "active"):
    url = f"{BASE}/teams/{team_id}/roster"
    resp = requests.get(url, params={"rosterType": roster_type}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("roster", [])


def get_player_recent_hitting(player_id: int, season: int, last_n_games: int = 15):
    """
    Return aggregated recent hitting rate stats over the player's last N
    games played this season (AVG, hits/game, AB/game, HR rate, etc.)
    """
    url = f"{BASE}/people/{player_id}/stats"
    params = {"stats": "gameLog", "group": "hitting", "season": season}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    splits = []
    for stat_group in data.get("stats", []):
        splits.extend(stat_group.get("splits", []))

    # Most recent first
    splits = splits[-last_n_games:] if len(splits) > last_n_games else splits
    if not splits:
        return None

    totals = {
        "ab": 0, "hits": 0, "hr": 0, "so": 0, "bb": 0,
        "rbi": 0, "tb": 0, "sb": 0, "games": len(splits),
    }
    for s in splits:
        st = s["stat"]
        totals["ab"] += st.get("atBats", 0)
        totals["hits"] += st.get("hits", 0)
        totals["hr"] += st.get("homeRuns", 0)
        totals["so"] += st.get("strikeOuts", 0)
        totals["bb"] += st.get("baseOnBalls", 0)
        totals["rbi"] += st.get("rbi", 0)
        totals["tb"] += st.get("totalBases", 0)
        totals["sb"] += st.get("stolenBases", 0)

    games = max(totals["games"], 1)
    ab = max(totals["ab"], 1)
    return {
        "games": totals["games"],
        "ab_per_game": totals["ab"] / games,
        "avg": totals["hits"] / ab,
        "hr_rate": totals["hr"] / ab,
        "k_rate": totals["so"] / ab,
        "bb_rate": totals["bb"] / ab,
        # Direct per-game rates, used as Poisson lambdas for prop models
        "hits_per_game": totals["hits"] / games,
        "hr_per_game": totals["hr"] / games,
        "rbi_per_game": totals["rbi"] / games,
        "tb_per_game": totals["tb"] / games,
        "bb_per_game": totals["bb"] / games,
        "sb_per_game": totals["sb"] / games,
    }


def get_team_k_rate(team_id: int, season: int):
    """
    Team's season-to-date strikeout rate (SO / PA), used as a simple
    opponent-strength adjustment for pitcher strikeout props.
    """
    url = f"{BASE}/teams/{team_id}/stats"
    params = {"stats": "season", "group": "hitting", "season": season}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            st = split["stat"]
            pa = st.get("plateAppearances") or st.get("atBats")
            so = st.get("strikeOuts")
            if pa:
                return so / pa
    return None


# Rough MLB league-average strikeout rate (per plate appearance) to use
# as a baseline for the opponent adjustment factor. Update periodically.
LEAGUE_AVG_K_RATE = 0.225


LEAGUE_AVG_RUNS_PER_GAME = 4.5


def get_team_run_rates(team_id: int, season: int):
    """
    Season-to-date runs scored per game and runs allowed per game for a
    team. Used as the offense/defense inputs for the moneyline, run
    line, and total models.
    """
    url = f"{BASE}/teams/{team_id}/stats"

    hit_resp = requests.get(url, params={"stats": "season", "group": "hitting", "season": season}, timeout=15)
    hit_resp.raise_for_status()
    hit_data = hit_resp.json()

    pitch_resp = requests.get(url, params={"stats": "season", "group": "pitching", "season": season}, timeout=15)
    pitch_resp.raise_for_status()
    pitch_data = pitch_resp.json()

    runs_scored = games_hit = None
    for stat_group in hit_data.get("stats", []):
        for split in stat_group.get("splits", []):
            st = split["stat"]
            if st.get("runs") is not None and st.get("gamesPlayed"):
                runs_scored, games_hit = st["runs"], st["gamesPlayed"]

    runs_allowed = games_pitch = None
    for stat_group in pitch_data.get("stats", []):
        for split in stat_group.get("splits", []):
            st = split["stat"]
            if st.get("runs") is not None and st.get("gamesPlayed"):
                runs_allowed, games_pitch = st["runs"], st["gamesPlayed"]

    if not all([runs_scored, games_hit, runs_allowed, games_pitch]):
        return None

    return {
        "runs_per_game": runs_scored / games_hit,
        "runs_allowed_per_game": runs_allowed / games_pitch,
    }


def get_pitcher_recent(player_id: int, season: int, last_n_games: int = 5):

    """Return aggregated recent pitching stats (K/9, IP/start, ERA-ish) over last N starts."""
    url = f"{BASE}/people/{player_id}/stats"
    params = {"stats": "gameLog", "group": "pitching", "season": season}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    splits = []
    for stat_group in data.get("stats", []):
        splits.extend(stat_group.get("splits", []))

    splits = splits[-last_n_games:] if len(splits) > last_n_games else splits
    if not splits:
        return None

    totals = {"ip_outs": 0, "so": 0, "er": 0, "bb": 0, "h": 0, "games": len(splits)}
    for s in splits:
        st = s["stat"]
        ip_str = st.get("inningsPitched", "0.0")
        whole, _, frac = ip_str.partition(".")
        outs = int(whole) * 3 + int(frac or 0)
        totals["ip_outs"] += outs
        totals["so"] += st.get("strikeOuts", 0)
        totals["er"] += st.get("earnedRuns", 0)
        totals["bb"] += st.get("baseOnBalls", 0)
        totals["h"] += st.get("hits", 0)

    games = max(totals["games"], 1)
    ip = max(totals["ip_outs"] / 3, 0.1)
    return {
        "games": totals["games"],
        "ip_per_start": ip / games,
        "k_per_9": (totals["so"] / ip) * 9,
        "era_recent": (totals["er"] / ip) * 9,
        "whip_recent": (totals["bb"] + totals["h"]) / ip,
        # Direct per-start rates, used as Poisson lambdas for prop models
        "k_total_per_start": totals["so"] / games,
        "h_per_start": totals["h"] / games,
        "bb_per_start": totals["bb"] / games,
        "er_per_start": totals["er"] / games,
        "outs_per_start": (ip / games) * 3,
    }
