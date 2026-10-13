"""European Black--Scholes pricing and basic option-risk mathematics.

Rates, volatility, and dividend yield are annual decimals. Greeks are for one
share and per 1.00 change in the input (vega/rho can be divided by 100 for a
one-percentage-point change).
"""
import math


def _cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes(spot, strike, time_years, risk_free_rate, volatility,
                  option_type="call", dividend_yield=0.0):
    """Return price and Greeks for a European call/put with continuous yield."""
    vals = (spot, strike, time_years, risk_free_rate, volatility, dividend_yield)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValueError("all inputs must be finite")
    if spot <= 0 or strike <= 0 or time_years < 0 or volatility < 0:
        raise ValueError("spot/strike must be positive; time/volatility nonnegative")
    kind = option_type.lower()
    if kind not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")
    if time_years == 0 or volatility == 0:
        disc = math.exp(-risk_free_rate * time_years)
        qdisc = math.exp(-dividend_yield * time_years)
        forward = spot * qdisc - strike * disc
        price = max(forward, 0.0) if kind == "call" else max(-forward, 0.0)
        delta = (qdisc if forward > 0 else 0.0) if kind == "call" else (-qdisc if forward < 0 else 0.0)
        return {"price": price, "delta": delta, "gamma": 0.0,
                "theta": 0.0, "vega": 0.0, "rho": 0.0}
    root_t = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * time_years) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    disc_r = math.exp(-risk_free_rate * time_years)
    disc_q = math.exp(-dividend_yield * time_years)
    pdf = _pdf(d1)
    if kind == "call":
        price = spot * disc_q * _cdf(d1) - strike * disc_r * _cdf(d2)
        delta = disc_q * _cdf(d1)
        theta = (-spot * disc_q * pdf * volatility / (2 * root_t)
                 - risk_free_rate * strike * disc_r * _cdf(d2)
                 + dividend_yield * spot * disc_q * _cdf(d1))
        rho = strike * time_years * disc_r * _cdf(d2)
    else:
        price = strike * disc_r * _cdf(-d2) - spot * disc_q * _cdf(-d1)
        delta = disc_q * (_cdf(d1) - 1)
        theta = (-spot * disc_q * pdf * volatility / (2 * root_t)
                 + risk_free_rate * strike * disc_r * _cdf(-d2)
                 - dividend_yield * spot * disc_q * _cdf(-d1))
        rho = -strike * time_years * disc_r * _cdf(-d2)
    return {"price": price, "delta": delta,
            "gamma": disc_q * pdf / (spot * volatility * root_t),
            "theta": theta / 365.0,
            "vega": spot * disc_q * pdf * root_t,
            "rho": rho}


def expected_move(spot, volatility, dte, basis=365.0):
    """One-standard-deviation move and range using IV * sqrt(DTE/year)."""
    if spot <= 0 or volatility < 0 or dte < 0 or basis <= 0:
        raise ValueError("spot/basis must be positive; volatility/DTE nonnegative")
    move = spot * volatility * math.sqrt(dte / basis)
    return {"move": move, "lower": spot - move, "upper": spot + move,
            "move_pct": move / spot}


POP_METHOD = "lognormal_risk_neutral"
POP_LIMITATIONS = (
    "Single-volatility lognormal: ignores skew, fat tails, jumps/earnings "
    "and early assignment; IV is a risk-neutral, not real-world, measure. "
    "Probability of finishing past break-even at expiration, not of "
    "touching it. Discrete dividends are approximated by a continuous yield.",
)


def lognormal_probability_between(spot, volatility, dte, lower=None, upper=None,
                                  rate=0.0, dividend_yield=0.0, basis=365.0):
    """P(lower <= S_T <= upper) for lognormal S_T (risk-neutral drift r - q).

    lower/upper of None mean 0 / infinity. With zero vol or zero DTE the
    terminal price is the deterministic forward, so the result is 0 or 1.
    """
    if spot <= 0 or volatility < 0 or dte < 0 or basis <= 0:
        raise ValueError("spot/basis must be positive; volatility/DTE nonnegative")
    lo = 0.0 if lower is None else max(0.0, lower)
    hi = math.inf if upper is None else upper
    if hi < lo:
        raise ValueError("upper must not be below lower")
    t = dte / basis
    drift = (rate - dividend_yield) * t
    sd = volatility * math.sqrt(t)
    if sd == 0:
        fwd = spot * math.exp(drift)
        return 1.0 if lo <= fwd <= hi else 0.0

    def cdf_at(level):
        if level <= 0:
            return 0.0
        if math.isinf(level):
            return 1.0
        z = (math.log(level / spot) - drift + 0.5 * sd * sd) / sd
        return _cdf(z)
    return max(0.0, min(1.0, cdf_at(hi) - cdf_at(lo)))


def estimate_pop(spot, volatility, dte, breakeven_low=None, breakeven_high=None,
                 rate=0.0, dividend_yield=0.0, basis=365.0):
    """Distribution-based POP for a break-even interval, with provenance.

    Vertical: pass one break-even (low for a bull put -> profit above it,
    high for a bear call -> profit below it). Condor: pass both.
    """
    if breakeven_low is None and breakeven_high is None:
        raise ValueError("at least one break-even is required")
    pop = lognormal_probability_between(spot, volatility, dte, breakeven_low,
                                        breakeven_high, rate, dividend_yield,
                                        basis)
    return {
        "pop": pop,
        "method": POP_METHOD,
        "assumptions": {"spot": spot, "iv": volatility, "dte": dte,
                        "rate": rate, "dividend_yield": dividend_yield,
                        "day_basis": basis,
                        "breakeven_low": breakeven_low,
                        "breakeven_high": breakeven_high},
        "expected_move": expected_move(spot, volatility, dte, basis),
        "limitations": list(POP_LIMITATIONS),
    }


def expected_move_candidates(spot, volatility, dte, strikes=None,
                             short_multiples=(1.0, 1.25, 1.5),
                             width_fractions=(0.10, 0.15, 0.25), basis=365.0):
    """Expected-move-driven short-strike and width candidates.

    Short put/call targets sit at spot -/+ m * expected move for each
    multiple m. Widths are fractions of the expected move. If a strike
    grid is given, targets snap to the nearest listed strike on the OTM
    side (puts down, calls up) and widths to the nearest positive strike
    spacing multiple. Returns sorted, de-duplicated lists.
    """
    em = expected_move(spot, volatility, dte, basis)
    move = em["move"]
    grid = sorted({float(k) for k in strikes if k > 0}) if strikes else None
    puts, calls = set(), set()
    for m in short_multiples:
        if m <= 0:
            raise ValueError("multiples must be positive")
        put_t, call_t = spot - m * move, spot + m * move
        if grid:
            below = [k for k in grid if k <= put_t and k < spot]
            above = [k for k in grid if k >= call_t and k > spot]
            if below:
                puts.add(below[-1])
            if above:
                calls.add(above[0])
        elif put_t > 0:
            puts.add(round(put_t, 2))
            calls.add(round(call_t, 2))
    widths = set()
    step = None
    if grid and len(grid) > 1:
        step = min(b - a for a, b in zip(grid, grid[1:]))
    for f in width_fractions:
        if f <= 0:
            raise ValueError("width fractions must be positive")
        w = f * move
        if step:
            w = max(step, round(w / step) * step)
        if w > 0:
            widths.add(round(w, 2))
    return {"expected_move": em, "put_short_strikes": sorted(puts),
            "call_short_strikes": sorted(calls), "widths": sorted(widths)}


def fractional_kelly(win_probability, max_gain, max_loss, fraction=0.25,
                     max_fraction=0.02):
    """Return full/fractional Kelly and capped bankroll fraction for binary risk."""
    if not 0 <= win_probability <= 1 or max_gain <= 0 or max_loss <= 0:
        raise ValueError("probability must be in [0,1] and payoffs positive")
    if not 0 < fraction <= 1 or not 0 < max_fraction <= 1:
        raise ValueError("Kelly fraction and cap must be in (0,1]")
    odds = max_gain / max_loss
    full = max(0.0, win_probability - (1.0 - win_probability) / odds)
    fractional = full * fraction
    return {"full_kelly": full, "fractional_kelly": fractional,
            "capped_fraction": min(fractional, max_fraction)}
