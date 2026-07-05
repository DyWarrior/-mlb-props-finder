"""
main.py
CLI entry point. Run:

    python main.py --api-key YOUR_ODDS_API_KEY
    python main.py --api-key YOUR_ODDS_API_KEY --min-edge 0.05 --date 2026-07-04

You can also set the ODDS_API_KEY environment variable instead of
passing --api-key.
"""
import argparse
import os
import sys

import analyzer


def main():
    parser = argparse.ArgumentParser(description="Find MLB props with the biggest model-vs-market edge.")
    parser.add_argument("--api-key", default=os.environ.get("ODDS_API_KEY"),
                         help="The Odds API key (or set ODDS_API_KEY env var)")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--min-edge", type=float, default=0.03,
                         help="Minimum model-vs-market edge to display (default 0.03 = 3%%)")
    parser.add_argument("--top", type=int, default=20, help="Max number of props to show")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: no API key. Pass --api-key or set ODDS_API_KEY.")
        print("Get a free key at https://the-odds-api.com")
        sys.exit(1)

    print(f"Researching MLB props for {args.date or 'today'} ...\n")
    rows = analyzer.run(args.api_key, target_date=args.date, min_edge=args.min_edge)

    if not rows:
        print("No props cleared the minimum edge threshold (or no data available).")
        print("Try lowering --min-edge, or check that games are scheduled for this date.")
        return

    print(f"{'PLAYER':<22}{'PROP':<24}{'BOOK':<18}{'ODDS':>7}{'MODEL%':>9}{'MKT%':>8}{'EDGE':>8}")
    print("-" * 96)
    for r in rows[: args.top]:
        print(f"{r['player'][:21]:<22}{r['prop'][:23]:<24}{r['book'][:17]:<18}"
              f"{r['odds']:>7}{r['model_prob']*100:>8.1f}%{r['market_fair_prob']*100:>7.1f}%"
              f"{r['edge']*100:>7.1f}%")

    print("\nNote: 'edge' = model probability minus the sportsbook's de-vigged fair "
          "probability. Positive edge = model thinks the outcome is more likely than "
          "the market's price implies. This is a starting point for research, not a "
          "guarantee — always sanity-check injuries, lineups, weather, and bullpen news "
          "before betting.")


if __name__ == "__main__":
    main()
