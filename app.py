"""
app.py
Runs MLB Props Finder as a local web app.

    python app.py

Then open http://127.0.0.1:5000 in your browser. Enter your Odds API
key in the page (it's kept in your browser only, never written to disk
by this app) and click "Find Props."
"""
import os

"""
app.py
Runs MLB Props Finder as a local web app.

    python app.py

Then open http://127.0.0.1:5000 in your browser. Enter your Odds API
key in the page (it's kept in your browser only, never written to disk
by this app) and click "Find Props."

Password protection: set the APP_PASSWORD environment variable to
require a password before the app is usable. If APP_PASSWORD isn't
set, the app falls back to a default password ("changeme") and prints
a warning — fine for quick local testing, but set your own password
before deploying anywhere public (e.g. Render).
"""
import functools
import os
import secrets

from flask import Flask, render_template, request, jsonify, session, redirect, url_for

import analyzer

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

APP_PASSWORD = os.environ.get("APP_PASSWORD")
if not APP_PASSWORD:
    APP_PASSWORD = "changeme"
    print("\n  WARNING: APP_PASSWORD not set — using default password 'changeme'.")
    print("  Set your own before deploying anywhere public, e.g.:")
    print("    export APP_PASSWORD=your_password_here\n")


def login_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not logged in."}), 401
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authed"] = True
            return redirect(url_for("index"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    data = request.get_json(force=True)
    api_key = (data.get("api_key") or "").strip()
    target_date = (data.get("date") or "").strip() or None
    min_edge = float(data.get("min_edge", 0.03))

    if not api_key:
        return jsonify({"error": "Missing API key. Get a free one at the-odds-api.com."}), 400

    try:
        rows = analyzer.run(api_key, target_date=target_date, min_edge=min_edge)
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg:
            msg = "API key was rejected. Double-check it's correct and active."
        elif "429" in msg:
            msg = "The Odds API rate/quota limit was hit. Check your usage at the-odds-api.com."
        return jsonify({"error": msg}), 500

    return jsonify({"rows": rows, "count": len(rows)})


@app.route("/api/team-bets", methods=["POST"])
@login_required
def api_team_bets():
    data = request.get_json(force=True)
    api_key = (data.get("api_key") or "").strip()
    target_date = (data.get("date") or "").strip() or None
    min_edge = float(data.get("min_edge", 0.02))

    if not api_key:
        return jsonify({"error": "Missing API key. Get a free one at the-odds-api.com."}), 400

    try:
        rows = analyzer.run_team_bets(api_key, target_date=target_date, min_edge=min_edge)
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg:
            msg = "API key was rejected. Double-check it's correct and active."
        elif "429" in msg:
            msg = "The Odds API rate/quota limit was hit. Check your usage at the-odds-api.com."
        return jsonify({"error": msg}), 500

    return jsonify({"rows": rows, "count": len(rows)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  MLB Props Finder running.")
    print(f"  On this computer:      http://127.0.0.1:{port}")
    print(f"  On your phone (same WiFi): http://<this-computer's-local-IP>:{port}")
    print("  (see README for how to find your local IP)\n")
    app.run(debug=False, host="0.0.0.0", port=port)
