"""
analyzer.py
Orchestrates the pipeline: schedule -> odds -> player stats -> model
probabilities -> ranked list of props with the biggest edge vs. the
market's fair (de-vigged) price.
"""
import re
from datetime import date

import mlb_data
import odds_data
import models


def normalize(name: str) -> str:
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r"[^a-z\s]", "", name)
    return " ".join(name.split())


def match_team(odds_team_name: str, mlb_games: list, side: str):
    """Find the MLB schedule entry matching an Odds API team name."""
    target = normalize(odds_team_name)
    for g in mlb_games:
        if normalize(g[f"{side}_team"]) == target:
            return g
    # fallback: partial match (last word, e.g. "Yankees")
    for g in mlb_games:
        if target.split()[-1] == normalize(g[f"{side}_team"]).split()[-1]:
            return g
    return None


# Batter prop markets we know how to model, mapped to the per-game rate
# field produced by mlb_data.get_player_recent_hitting().
BATTER_MARKET_CONFIG = {
    "batter_hits": {"label": "Hits", "lambda_key": "hits_per_game"},
    "batter_home_runs": {"label": "Home Runs", "lambda_key": "hr_per_game"},
    "batter_rbis": {"label": "RBIs", "lambda_key": "rbi_per_game"},
    "batter_total_bases": {"label": "Total Bases", "lambda_key": "tb_per_game"},
    "batter_walks": {"label": "Walks", "lambda_key": "bb_per_game"},
    "batter_stolen_bases": {"label": "Stolen Bases", "lambda_key": "sb_per_game"},
}

# Pitcher prop markets, mapped to the per-start rate field produced by
# mlb_data.get_pitcher_recent(). "opponent_adjustable" props get scaled
# by the opposing team's strikeout rate vs. league average; the rest
# use the pitcher's raw recent rate (no reliable opponent signal wired
# up yet for hits/walks/earned runs allowed).
PITCHER_MARKET_CONFIG = {
    "pitcher_strikeouts": {"label": "Strikeouts", "lambda_key": "k_total_per_start", "opponent_adjustable": True},
    "pitcher_hits_allowed": {"label": "Hits Allowed", "lambda_key": "h_per_start", "opponent_adjustable": False},
    "pitcher_walks": {"label": "Walks", "lambda_key": "bb_per_start", "opponent_adjustable": False},
    "pitcher_earned_runs": {"label": "Earned Runs", "lambda_key": "er_per_start", "opponent_adjustable": False},
    "pitcher_outs": {"label": "Outs Recorded", "lambda_key": "outs_per_start", "opponent_adjustable": False},
}


def _devig_pair(outcome_a, outcome_b):
    """De-vig any two complementary outcomes (Over/Under, or Team A/Team B)."""
    p_a_raw = models.american_to_prob(outcome_a["price"])
    p_b_raw = models.american_to_prob(outcome_b["price"])
    return models.devig_two_way(p_a_raw, p_b_raw)


def build_pitcher_prop_rows(game, season, opp_k_rate, event_odds):
    rows = []
    for side, pitcher_key, opp_team_key in [
        ("home", "home_pitcher_id", "away_team_id"),
        ("away", "away_pitcher_id", "home_team_id"),
    ]:
        pid = game.get(pitcher_key)
        if not pid:
            continue
        recent = mlb_data.get_pitcher_recent(pid, season)
        if not recent:
            continue
        pitcher_name = game["home_pitcher"] if side == "home" else game["away_pitcher"]
        team_name = game["home_team"] if side == "home" else game["away_team"]

        k_factor = 1.0
        if opp_k_rate.get(game[opp_team_key]):
            k_factor = opp_k_rate[game[opp_team_key]] / mlb_data.LEAGUE_AVG_K_RATE

        for bm in event_odds.get("bookmakers", []):
            for market in bm.get("markets", []):
                config = PITCHER_MARKET_CONFIG.get(market["key"])
                if not config:
                    continue

                over_o = next((o for o in market["outcomes"]
                                if normalize(o.get("description", "")) == normalize(pitcher_name)
                                and normalize(o["name"]) == "over"), None)
                under_o = next((o for o in market["outcomes"]
                                 if normalize(o.get("description", "")) == normalize(pitcher_name)
                                 and normalize(o["name"]) == "under"), None)
                if not over_o or not under_o:
                    continue

                line = over_o["point"]
                fair_over, fair_under = _devig_pair(over_o, under_o)

                adjustment = k_factor if config["opponent_adjustable"] else 1.0
                model_p_over = models.project_count_stat_over(
                    recent.get(config["lambda_key"]), line, adjustment
                )
                e = models.edge(model_p_over, fair_over)

                rows.append({
                    "player": pitcher_name,
                    "team": team_name,
                    "matchup": f"{game['away_team']} @ {game['home_team']}",
                    "prop": f"{config['label']} Over {line}",
                    "book": bm["title"],
                    "odds": over_o["price"],
                    "market_fair_prob": round(fair_over, 3),
                    "model_prob": round(model_p_over, 3) if model_p_over is not None else None,
                    "edge": round(e, 3) if e is not None else None,
                })
    return rows


def build_batter_prop_rows(game, season, event_odds, roster_cache):
    rows = []

    for team_id in (game["home_team_id"], game["away_team_id"]):
        if team_id not in roster_cache:
            roster_cache[team_id] = mlb_data.get_team_roster(team_id)

    name_to_id = {}
    name_to_team = {}
    for team_id, team_name in [(game["home_team_id"], game["home_team"]),
                                (game["away_team_id"], game["away_team"])]:
        for p in roster_cache[team_id]:
            norm_name = normalize(p["person"]["fullName"])
            name_to_id[norm_name] = p["person"]["id"]
            name_to_team[norm_name] = team_name

    for bm in event_odds.get("bookmakers", []):
        for market in bm.get("markets", []):
            config = BATTER_MARKET_CONFIG.get(market["key"])
            if not config:
                continue

            outcomes_by_player = {}
            for o in market.get("outcomes", []):
                pname = o.get("description")
                outcomes_by_player.setdefault(normalize(pname), {})[normalize(o["name"])] = o

            for pname_norm, sides in outcomes_by_player.items():
                over_o, under_o = sides.get("over"), sides.get("under")
                if not over_o or not under_o:
                    continue
                pid = name_to_id.get(pname_norm)
                if not pid:
                    continue
                recent = mlb_data.get_player_recent_hitting(pid, season)
                if not recent:
                    continue

                line = over_o["point"]
                fair_over, fair_under = _devig_pair(over_o, under_o)

                model_p_over = models.project_count_stat_over(
                    recent.get(config["lambda_key"]), line
                )
                e = models.edge(model_p_over, fair_over)

                rows.append({
                    "player": over_o.get("description"),
                    "team": name_to_team.get(pname_norm, "?"),
                    "matchup": f"{game['away_team']} @ {game['home_team']}",
                    "prop": f"{config['label']} Over {line}",
                    "book": bm["title"],
                    "odds": over_o["price"],
                    "market_fair_prob": round(fair_over, 3),
                    "model_prob": round(model_p_over, 3) if model_p_over is not None else None,
                    "edge": round(e, 3) if e is not None else None,
                })
    return rows


def run(api_key: str, season: int = None, target_date: str = None, min_edge: float = 0.03):
    season = season or date.today().year
    schedule = mlb_data.get_schedule(target_date)
    if not schedule:
        return []

    events = odds_data.get_events(api_key)
    opp_k_rate_cache = {}
    roster_cache = {}
    all_rows = []

    for ev in events:
        game = match_team(ev["home_team"], schedule, "home")
        if not game:
            continue

        for tid in (game["home_team_id"], game["away_team_id"]):
            if tid not in opp_k_rate_cache:
                opp_k_rate_cache[tid] = mlb_data.get_team_k_rate(tid, season)

        try:
            event_odds = odds_data.get_player_props(api_key, ev["id"])
        except Exception as exc:
            print(f"  (skipping props for {ev['home_team']} vs {ev['away_team']}: {exc})")
            continue

        all_rows.extend(build_pitcher_prop_rows(game, season, opp_k_rate_cache, event_odds))
        all_rows.extend(build_batter_prop_rows(game, season, event_odds, roster_cache))

    ranked = [r for r in all_rows if r["edge"] is not None and r["edge"] >= min_edge]
    ranked.sort(key=lambda r: r["edge"], reverse=True)
    return ranked


def _team_row(label, team, matchup, prop_label, book, price, fair_prob, model_prob):
    e = models.edge(model_prob, fair_prob)
    return {
        "player": label,
        "team": team,
        "matchup": matchup,
        "prop": prop_label,
        "book": book,
        "odds": price,
        "market_fair_prob": round(fair_prob, 3) if fair_prob is not None else None,
        "model_prob": round(model_prob, 3) if model_prob is not None else None,
        "edge": round(e, 3) if e is not None else None,
    }


HOME_FIELD_BUMP = 1.03   # home team scores ~3% more than a neutral-field expectation
AWAY_FIELD_BUMP = 0.97   # away team scores ~3% less


def build_team_bet_rows(game, home_rates, away_rates, game_odds_entry):
    """
    Moneyline, run line (spread), and total runs models for a single
    game, using a Monte Carlo simulation of team scoring built from
    each team's season run-scoring/run-prevention rates.
    """
    rows = []
    if not home_rates or not away_rates:
        return rows

    lambda_home = models.expected_runs(
        home_rates["runs_per_game"], away_rates["runs_allowed_per_game"],
        mlb_data.LEAGUE_AVG_RUNS_PER_GAME, HOME_FIELD_BUMP,
    )
    lambda_away = models.expected_runs(
        away_rates["runs_per_game"], home_rates["runs_allowed_per_game"],
        mlb_data.LEAGUE_AVG_RUNS_PER_GAME, AWAY_FIELD_BUMP,
    )
    if lambda_home is None or lambda_away is None:
        return rows

    sim = models.simulate_game(lambda_home, lambda_away)
    total_lambda = lambda_home + lambda_away
    home_name, away_name = game["home_team"], game["away_team"]

    for bm in game_odds_entry.get("bookmakers", []):
        for market in bm.get("markets", []):
            key = market["key"]
            outcomes = market.get("outcomes", [])
            if len(outcomes) != 2:
                continue

            if key == "h2h":
                home_o = next((o for o in outcomes if normalize(o["name"]) == normalize(home_name)), None)
                away_o = next((o for o in outcomes if normalize(o["name"]) == normalize(away_name)), None)
                if not home_o or not away_o:
                    continue
                fair_home, fair_away = _devig_pair(home_o, away_o)
                model_home = sim["home_win_prob"]
                matchup = f"{away_name} @ {home_name}"
                rows.append(_team_row(home_name, "", matchup, "Moneyline", bm["title"], home_o["price"], fair_home, model_home))
                rows.append(_team_row(away_name, "", matchup, "Moneyline", bm["title"], away_o["price"], fair_away, 1 - model_home))

            elif key == "spreads":
                home_o = next((o for o in outcomes if normalize(o["name"]) == normalize(home_name)), None)
                away_o = next((o for o in outcomes if normalize(o["name"]) == normalize(away_name)), None)
                if not home_o or not away_o:
                    continue
                fair_home, fair_away = _devig_pair(home_o, away_o)
                # margin = home_runs - away_runs; a team "covers" its point P if
                # (their runs + P) beat the opponent's runs.
                model_home_cover = models.empirical_prob_gt(sim["margins"], -home_o["point"])
                model_away_cover = models.empirical_prob_lt(sim["margins"], away_o["point"])
                matchup = f"{away_name} @ {home_name}"
                rows.append(_team_row(home_name, "", matchup, f"Run Line {home_o['point']:+g}", bm["title"],
                                       home_o["price"], fair_home, model_home_cover))
                rows.append(_team_row(away_name, "", matchup, f"Run Line {away_o['point']:+g}", bm["title"],
                                       away_o["price"], fair_away, model_away_cover))

            elif key == "totals":
                over_o = next((o for o in outcomes if normalize(o["name"]) == "over"), None)
                under_o = next((o for o in outcomes if normalize(o["name"]) == "under"), None)
                if not over_o or not under_o:
                    continue
                fair_over, fair_under = _devig_pair(over_o, under_o)
                model_over = models.poisson_p_over_line(total_lambda, over_o["point"])
                matchup = f"{away_name} @ {home_name}"
                rows.append(_team_row(matchup, "", matchup, f"Total Over {over_o['point']}", bm["title"],
                                       over_o["price"], fair_over, model_over))
                rows.append(_team_row(matchup, "", matchup, f"Total Under {under_o['point']}", bm["title"],
                                       under_o["price"], fair_under, 1 - model_over if model_over is not None else None))
    return rows


def run_team_bets(api_key: str, season: int = None, target_date: str = None, min_edge: float = 0.02):
    """
    Ranked moneyline / run line / total picks. Note this only needs a
    single bulk odds request (unlike player props, which need one
    request per event), so it's much lighter on your API quota.
    """
    season = season or date.today().year
    schedule = mlb_data.get_schedule(target_date)
    if not schedule:
        return []

    game_odds_data = odds_data.get_game_odds(api_key)
    team_rates_cache = {}
    all_rows = []

    for go in game_odds_data:
        game = match_team(go["home_team"], schedule, "home")
        if not game:
            continue

        for tid in (game["home_team_id"], game["away_team_id"]):
            if tid not in team_rates_cache:
                team_rates_cache[tid] = mlb_data.get_team_run_rates(tid, season)

        home_rates = team_rates_cache.get(game["home_team_id"])
        away_rates = team_rates_cache.get(game["away_team_id"])
        all_rows.extend(build_team_bet_rows(game, home_rates, away_rates, go))

    ranked = [r for r in all_rows if r["edge"] is not None and r["edge"] >= min_edge]
    ranked.sort(key=lambda r: r["edge"], reverse=True)
    return ranked


def run_game_lines(api_key: str):
    """Simple moneyline/total value scan (no player-level modeling, just
    surfaces line discrepancies across books for you to review)."""
    data = odds_data.get_game_odds(api_key)
    out = []
    for game in data:
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                out.append({
                    "matchup": f"{game['away_team']} @ {game['home_team']}",
                    "market": market["key"],
                    "book": bm["title"],
                    "outcomes": [(o["name"], o.get("point"), o["price"]) for o in market["outcomes"]],
                })
    return out
