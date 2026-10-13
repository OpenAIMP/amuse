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
