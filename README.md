# MLB Props Finder

A tool that researches upcoming MLB games and surfaces player props / team
lines where a simple statistical model disagrees with the sportsbook's
implied probability — i.e. potential value, ranked by edge.

## How it works

1. **Schedule & stats** — pulled from the free, public MLB Stats API (no key needed):
   probable pitchers, each batter's rolling recent performance (last 15 games),
   each pitcher's rolling recent performance (last 5 starts), and team strikeout
   rates (used to adjust for opponent quality).
2. **Odds & props** — pulled from [The Odds API](https://the-odds-api.com)
   (free tier: 500 requests/month). You need your own free API key.
3. **Modeling** — recent performance is converted into a Poisson-based
   probability for each prop (e.g. "P(batter gets ≥1 hit)",
   "P(pitcher strikeouts > 5.5)"). The sportsbook's odds are converted to an
   implied probability and de-vigged (the standard method: normalize both
   sides of a two-way market so they sum to 100%).
4. **Edge** = model probability − market's fair probability. Props are
   ranked by edge, highest first.

## Password protection

The app requires a password before it's usable — useful once you deploy it
somewhere public (like Render) since anyone with the URL could otherwise
use it (and burn through your API quota).

**Set your own password** via an environment variable before running:
```bash
export APP_PASSWORD=your_own_password_here
python app.py
```

If you don't set one, it falls back to the default password `changeme` and
prints a warning — fine for a quick local test, but **set a real password
before deploying anywhere public.**

On Render specifically, add `APP_PASSWORD` under your Web Service's
"Environment" tab (Environment → Add Environment Variable) rather than in
your code, so it isn't sitting in your public GitHub repo.

## Using it on your phone

The app runs on your computer, but your phone can connect to it over the
same WiFi network — you don't need to install anything on the phone.

**1. Find your computer's local network IP address:**

Mac:
```bash
ipconfig getifaddr en0
```
(if that prints nothing, try `en1` instead of `en0`)

Windows (Command Prompt):
```bash
ipconfig
```
Look for "IPv4 Address" under your active WiFi adapter (something like `192.168.1.42`).

**2. Make sure your phone is on the same WiFi network as your computer.**

**3. Start the app** as usual:
```bash
python3 app.py
```

**4. On your phone's browser**, go to:
```
http://<the-IP-from-step-1>:5000
```
e.g. `http://192.168.1.42:5000`

**Troubleshooting:**
- **Can't connect / times out** — your computer's firewall may be blocking incoming connections. On Mac: System Settings → Network → Firewall, and either turn it off temporarily or allow incoming connections for Python. On Windows: allow Python through Windows Defender Firewall when prompted.
- **Still nothing** — some routers isolate devices from each other for security ("AP/client isolation" or "guest network" mode). Try a non-guest WiFi network, or check your router settings.
- This only works while your computer is on and `app.py` is running, and only for devices on the same local network — it's not accessible from the internet at large.

## Setup

```bash
pip install -r requirements.txt
```

Get a free API key at https://the-odds-api.com (sign up, no credit card
needed for the free tier).

## Usage — Web App (recommended)

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser. Enter your Odds API key,
pick a date and minimum edge threshold, and click "Find Props." Results show
up in a sortable-by-edge table right in the page. Your API key stays in your
browser (optionally saved via the "remember key" checkbox) — it's only ever
sent to this local app and to The Odds API itself.

To stop the app, go back to the terminal and press `Ctrl+C`.

## Usage — Command Line (alternative)

```bash
export ODDS_API_KEY=your_key_here
python main.py
```

Or pass it directly:

```bash
python main.py --api-key your_key_here --min-edge 0.05 --top 15
```

Options:
- `--date YYYY-MM-DD` — target a specific day (default: today)
- `--min-edge 0.03` — only show props with at least this much edge (0.03 = 3%)
- `--top 20` — max rows to display

## Team bets (Moneyline, Run Line, Total)

Alongside player props, the app also models team-level bets:

- **Moneyline** — win probability from a Monte Carlo simulation of the game, using each team's season runs-scored and runs-allowed rates (a log5-style adjustment), with a small home-field bump.
- **Run Line (spread)** — cover probability for either side's run line, from the same simulation.
- **Total (Over/Under)** — since the sum of two independent Poisson variables is itself Poisson, this uses the combined expected-runs rate directly (no simulation needed) to compute over/under probability for any total line.

This only takes **one bulk API request** for all of a day's games (much lighter than player props, which need one request per game). Use the "Find Team Bets" button in the app, or `analyzer.run_team_bets()` from Python directly.

## What's currently modeled

All of the below use a Poisson model based on the player's recent per-game
(or per-start) rate for that stat, and work for **any** line the sportsbook
posts (0.5, 1.5, 2.5, etc.), not just "at least 1."

**Batter props:**
- Hits
- Home runs
- RBIs
- Total bases
- Walks
- Stolen bases

**Pitcher props:**
- Strikeouts (adjusted for opponent team strikeout rate vs. league average)
- Hits allowed
- Walks
- Earned runs
- Outs recorded

Game lines (moneyline/spread/total) can be pulled via `analyzer.run_game_lines()`,
though no model is applied to them yet — it just lets you compare odds across books.

Note: not every sportsbook offers every one of these markets for every game —
if a market comes back empty, it's usually a coverage gap on the book's side,
not a bug. Market key names on The Odds API can also shift over time; if a
market key stops matching, check
https://the-odds-api.com/sports-odds-data/betting-markets.html for the current
names and update `PLAYER_PROP_MARKETS` in `odds_data.py` accordingly.

## Extending it

The codebase is split so you can improve pieces independently:
- `mlb_data.py` — add park factors, platoon splits (vs. LHP/RHP), weather, injury/lineup checks
- `models.py` — swap the simple Poisson models for something more sophisticated
  (e.g. regression using exit velocity / Statcast data, or a proper backtested model)
- `analyzer.py` — add more prop markets (RBIs, total bases with real line support,
  stolen bases, runs), or add multi-book line shopping to find the best price
  on top of the best edge

## Important limitations & disclaimer

- **This is a research aid, not a guarantee.** The probability models are
  intentionally simple (recent-performance Poisson approximations). They
  don't account for weather, ballpark, lineup changes, injuries, bullpen
  usage, or platoon splits unless you extend them to.
- **Small sample sizes.** "Last 15 games" of hitting stats or "last 5 starts"
  of pitching stats can be noisy. Treat a positive edge as "worth investigating
  further," not as a bet recommendation.
- **Name matching** between the MLB Stats API and The Odds API is done via
  normalized string matching. It's usually reliable but can occasionally miss
  a player (e.g. suffixes like "Jr." or accented characters) — those rows will
  just be skipped rather than silently wrong.
- **API costs**: The Odds API's free tier is limited (500 requests/month), and
  this tool makes one request per game to fetch player props. Running it
  daily across a full slate can add up — check your usage on their dashboard.
- Sports betting involves financial risk. Past performance doesn't guarantee
  future results, and no model — including this one — can eliminate variance.
  Bet only what you can afford to lose, and use tools like bankroll limits or
  self-exclusion if betting stops feeling fun. If it ever feels out of control,
  the National Council on Problem Gambling helpline is 1-800-522-4700.
