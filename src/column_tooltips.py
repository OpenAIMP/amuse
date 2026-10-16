"""
Shared column header tooltips for all report renderers.

Maps column display names to plain-English explanations.
Used by render_report.py, render_compare.py, render_hub.py.
"""

TOOLTIPS = {
    # === Stock screener ===
    "Symbol": "Underlying symbol. Click for quote pages.",
    "Sym": "Underlying symbol. Click for quote pages.",
    "Price": "Last price at screen time.",
    "Score": "Composite 0-40: base 0-30 (indicators) + signals 0-10. Higher = better setup.",
    "Verdict": "Go for it (25+, UP/RNG + bullish) / Watch (20+, misses a Go criterion) / Pass.",
    "Trend": "UP (price > SMA50 > SMA200) / DN (below both) / RNG (mixed).",
    "RSI": "Relative Strength Index (14). >70 = overbought, <30 = oversold.",
    "RSI14": "Relative Strength Index (14). >70 = overbought, <30 = oversold.",
    "SMA50": "Distance from 50-day moving average (%). Positive = above.",
    "SMA200": "Distance from 200-day moving average (%).",
    "ATR%": "Average True Range as % of price. Higher = more volatile.",
    "Volume": "Volume ratio vs 20-day average. >1.5 = unusual activity.",
    "Off high": "Distance from 52-week high (%). Negative = below high.",
    "%B": "Bollinger %B: position within bands. >1 = above upper, <0 = below lower.",
    "Bias": "Bullish / Bearish / Neutral from indicator confluence.",
    "30d": "30-day return (%).",
    "YTD": "Year-to-date return (%).",
    "1d": "1-day return (%).",

    # === Spread screener ===
    "Exp": "Option expiration date.",
    "Strikes": "Short strike / long strike. First = sold, second = bought.",
    "Strike": "Option strike price.",
    "Wings": "Wing widths for iron condor (put wing / call wing).",
    "DTE": "Days to expiration.",
    "Credit": "Net credit received (per share x 100 = total).",
    "Debit": "Net debit paid (per share x 100 = total).",
    "Debit/Credit": "Net debit (long strategies) or credit (short strategies).",
    "Max loss": "Maximum loss if trade goes fully against you.",
    "Max profit": "Maximum profit if trade goes fully in your favor.",
    "Breakeven": "Underlying price where the trade breaks even at expiration.",
    "RoR": "Return on risk: credit ? max loss. Ranking ratio, not expected return.",
    "Win%": "Delta-based probability of profit. Model estimate, not guarantee.",
    "EV$": "Expected value in dollars: P(win)xcredit - P(loss)xmax loss - friction.",
    "Lossx": "Loss multiple: max loss ? credit. Higher = more risk per dollar.",
    "Lucrative": "Lucrative (Win% 70%+, +EV, <=3x) / Solid / Negative EV / High risk / Marginal.",
    "Events": "Earnings or binary events in window. Any flag = disqualified.",
    "Risk": "Defined (max loss capped) or Undefined (naked - unlimited risk).",
    "Short exp": "Short option expiration.",
    "Long exp": "Long option expiration.",
    "Structure": "Option strategy structure.",
    "Recommendation": "Trade recommendation from decision engine.",
    "1sigma expected move ($)": "One standard deviation expected move in dollars.",
    "Kelly sizing": "Kelly criterion suggested position size.",
    "Six decision gates": "Pass/fail on the six decision gates.",
    "Best strategy": "Highest-EV strategy for this symbol.",
    "Rank": "Rank among all strategies for this symbol.",
    "Alternatives": "Other viable strategies for this symbol.",

    # === PMCC ===
    "Long / Short": "LEAPS long-call strike / short-call strike.",
    "Long / short strike": "LEAPS long-call strike / short-call strike.",
    "Long / short expiry": "LEAPS expiration / short-call expiration.",
    "P/D 30d": "Premium-to-debit over 30 days (%). Monthly income as % of capital. Gate: >=4.0.",
    "Capital": "Total capital required (LEAPS debit + margin).",
    "Breach": "Short strike distance above spot (%). How far stock must rise to threaten short call. Gate: <=8%.",
    "Qualification": "Whether the pair meets all entry gates.",
    "Accepted": "Whether this pair was accepted for the watchlist.",
    "Reasons": "Why this pair qualified or was rejected.",
    "Evaluation details": "Detailed gate-by-gate evaluation.",

    # === Compare / Leaderboard ===
    "#": "Rank in this view.",
    "View": "Market view: bullish, bearish, neutral, or directional.",

    # === Premarket ===
    "Gap%": "Premarket gap vs prior close (%).",
    "Gap / ATR": "Absolute gap divided by ATR percentage. Normalized gap size.",
    "PM RVOL": "Premarket relative volume vs average.",
    "Prior close": "Previous day's closing price.",
    "Session data": "Premarket session high/low/volume.",
    "Conviction": "High / Medium / Low based on gap + volume confluence.",
    "OR high / low": "Opening range high / low (first 15 min).",
    "Pattern": "Technical pattern detected.",
    "What it means": "Plain-English interpretation of the pattern.",
    "Criteria (all must hold)": "All conditions required for this pattern.",
    "Missed gate": "Which entry gate was not met.",
    "Strategy": "Option strategy name.",
    "The edge it harvests": "What market inefficiency this strategy exploits.",
    "Underlying": "Underlying symbol.",
    "Scenario": "Price scenario at expiration.",
    "P&L": "Profit or loss in this scenario.",
    "Selection": "Why this was selected.",
}


def th(name, extra_attrs=""):
    """
    Generate a <th> tag with tooltip.

    Args:
        name: Column display name (looked up in TOOLTIPS)
        extra_attrs: Additional HTML attributes (e.g. 'class="num"')

    Returns:
        <th> HTML string with title tooltip if available.
    """
    tip = TOOLTIPS.get(name, "")
    title = f" title='{tip}'" if tip else ""
    attrs = f" {extra_attrs}" if extra_attrs else ""
    return f"<th{title}{attrs}>{name}</th>"


def th_row(names):
    """Generate a <tr> of <th> cells with tooltips."""
    return "<tr>" + "".join(th(n) for n in names) + "</tr>"
