"""
models.py
Simple statistical models to turn recent player performance into a
probability estimate for common prop bet lines, plus odds math to
compare against the sportsbook's implied probability.

These are intentionally simple (Poisson / binomial approximations).
They are a reasonable starting point, not a guarantee of accuracy.
Treat "edge" as a signal to investigate further, not a sure thing.
"""
import math
import random


def american_to_prob(odds: float) -> float:
    """Convert American odds to implied probability (includes vig)."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)


def devig_two_way(prob_a: float, prob_b: float):
    """
    Remove the vig from a two-sided market (e.g. Over/Under) assuming
    the overround is split proportionally. Returns (fair_a, fair_b).
    """
    total = prob_a + prob_b
    if total == 0:
        return prob_a, prob_b
    return prob_a / total, prob_b / total


def poisson_p_at_least(lam: float, k: int = 1) -> float:
    """P(X >= k) for X ~ Poisson(lambda)."""
    if lam <= 0:
        return 0.0
    p_less_than_k = sum(
        (lam ** i) * math.exp(-lam) / math.factorial(i) for i in range(k)
    )
    return 1 - p_less_than_k


def poisson_p_over_line(lam: float, line: float) -> float:
    """
    P(X > line) for a half-point line like 5.5 strikeouts, using a
    Poisson approximation for count-based stats (Ks, hits, total bases).
    """
    if lam <= 0:
        return 0.0
    threshold = math.floor(line) + 1  # smallest integer strictly greater than line
    return poisson_p_at_least(lam, threshold)


def project_count_stat_over(per_game_rate: float, line: float, adjustment_factor: float = 1.0) -> float:
    """
    Generic Poisson model for any count-based prop (hits, total bases,
    RBIs, home runs, stolen bases, strikeouts, walks, etc.). Works for
    any line (0.5, 1.5, 2.5, ...), not just "at least 1."

    per_game_rate: the player's recent average for this stat, per game/start
    line: the sportsbook's line (e.g. 1.5)
    adjustment_factor: optional multiplier for opponent strength
        (e.g. 1.05 = opponent allows/produces 5% more of this stat than average)
    """
    if per_game_rate is None:
        return None
    lam = per_game_rate * adjustment_factor
    return poisson_p_over_line(lam, line)


def opponent_adjustment_factor(opponent_rate: float, league_avg_rate: float) -> float:
    """Turn an opponent's season rate into a multiplier vs. league average."""
    if not opponent_rate or not league_avg_rate:
        return 1.0
    return opponent_rate / league_avg_rate


# Kept as a thin, explicit wrapper since strikeouts are the prop most
# people look for first; behaves identically to project_count_stat_over.
def project_pitcher_k_over(recent_pitching: dict, opponent_k_rate_vs_avg: float, line: float) -> float:
    if not recent_pitching:
        return None
    return project_count_stat_over(recent_pitching["k_total_per_start"], line, opponent_k_rate_vs_avg)


def edge(model_prob: float, fair_market_prob: float) -> float:
    """Positive = model thinks the outcome is more likely than the market's fair price."""
    if model_prob is None or fair_market_prob is None:
        return None
    return model_prob - fair_market_prob


# ---------------------------------------------------------------------
# Team bet models: moneyline (winner), run line (spread), total (over/under)
# ---------------------------------------------------------------------

def expected_runs(team_off_rate: float, opp_def_rate: float, league_avg: float,
                   home_field_adjustment: float = 1.0) -> float:
    """
    Simple log5-style run expectation: a team's expected runs scored is
    scaled by how much better/worse than league average their offense
    is, combined with how much better/worse than league average the
    opponent's run prevention is. home_field_adjustment nudges this up
    slightly for the home team, down slightly for the away team.
    """
    if not team_off_rate or not opp_def_rate or not league_avg:
        return None
    lam = league_avg * (team_off_rate / league_avg) * (opp_def_rate / league_avg)
    return lam * home_field_adjustment


def poisson_sample(lam: float) -> int:
    """Draw one sample from a Poisson(lambda) distribution (Knuth's algorithm)."""
    if lam <= 0:
        return 0
    threshold = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= threshold:
            return k - 1


def simulate_game(lambda_home: float, lambda_away: float, trials: int = 20000) -> dict:
    """
    Monte Carlo simulation of a game's final score, treating each team's
    runs as independent Poisson draws. Returns the home win probability
    plus the raw margin (home - away) and total (home + away) samples,
    so callers can compute cover probabilities against any sportsbook
    line (run line, total) without re-simulating per line.
    """
    margins = []
    totals = []
    home_win_count = 0.0
    for _ in range(trials):
        h = poisson_sample(lambda_home)
        a = poisson_sample(lambda_away)
        margins.append(h - a)
        totals.append(h + a)
        if h > a:
            home_win_count += 1
        elif h == a:
            home_win_count += 0.5  # extra innings approximated as a coin flip
    return {
        "home_win_prob": home_win_count / trials,
        "margins": margins,
        "totals": totals,
    }


def empirical_prob_gt(samples: list, threshold: float) -> float:
    return sum(1 for s in samples if s > threshold) / len(samples)


def empirical_prob_lt(samples: list, threshold: float) -> float:
    return sum(1 for s in samples if s < threshold) / len(samples)
