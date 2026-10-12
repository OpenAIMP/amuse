"""Shared gate configuration loader (stdlib-only).

Reads gates.yaml (next to this file, or --config PATH / GATES_CONFIG env)
and deep-merges it over DEFAULTS, so a missing or partial file can never
break a screener. Screeners import this instead of hardcoding thresholds.

The YAML subset supported (kept dependency-free on purpose):
  - `key: value` mappings, nested via 2-space indentation
  - scalar values: int, float, true/false, null
  - `#` comments, blank lines
  - no lists, no tabs, no multi-line values
Anything outside the subset raises ValueError with a line number.
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(_HERE, "gates.yaml")

DEFAULTS = {
    "spreads": {
        "dte_min": 21, "dte_max": 60,
        "short_delta_min": 0.10, "short_delta_max": 0.20,
        "width_min": 1.0, "width_max": 5.0, "width_divisor": 25,
        "max_spread_pct": 0.25, "min_liquidity": 10,
        "max_loss": 1000, "max_friction": 3.0,
        "call_distance_min": 0.08,
    },
    "stock": {
        "price_min": 10.0, "price_max": 500.0,
        "rsi_period": 14, "rsi_min": 30.0, "rsi_max": 70.0,
        "sma_fast": 50, "sma_slow": 200,
        "require_above_sma_fast": True, "require_above_sma_slow": True,
        "atr_pct_min": 1.0, "atr_pct_max": 6.0,
        "vol_ratio_min": 0.9, "max_off_high_pct": 25.0,
        "min_bars": 200,
        "bb_period": 20, "bb_mult": 2.0,
        "bb_pctb_min": 0.0, "bb_pctb_max": 1.0,
        "squeeze_lookback": 125, "min_bars_squeeze": 130,
        "require_above_anchored_vwap": True,
        "reject_downtrend": True,
        "pivot_n": 5, "swing_lookback_bars": 126,
        "ema_fast": 50, "ema_slow": 200,
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "cross_lookback": 20, "reject_death_cross": True,
        "gap_label_abs_pct": 2.0, "rsi_oversold": 30.0, "rsi_overbought": 70.0,
        "value_under_max_pct": 25.0, "value_over_min_pct": 75.0,
        "bias_bull_min": 4, "bias_bear_max": 2,
    },
    "premarket": {
        "gap_min_pct": 2.0, "rel_vol_min": 1.5, "price_min": 10.0,
        "atr_pct_min": 1.0, "atr_pct_max": 8.0,
        "top_n": 20, "min_daily_bars": 30,
    },
    "intraday": {
        "or_minutes": 15, "breakout_buffer_pct": 0.1,
        "rel_vol_min": 1.5, "price_min": 10.0,
        "atr_pct_min": 1.0, "atr_pct_max": 8.0,
        "top_n": 20, "min_daily_bars": 30, "vwap_lookback_bars": 6,
    },
    "pmcc": {
        "long_dte_min": 270, "long_dte_max": 800,
        "long_delta_min": 0.80, "long_delta_max": 0.95,
        "short_dte_min": 21, "short_dte_max": 60,
        "short_delta_min": 0.15, "short_delta_max": 0.35,
        "max_spread_pct": 0.25,
        "min_long_liquidity": 25, "min_short_liquidity": 10,
        "max_capital": 10000, "max_friction": 3.0,
    },
    "exits": {
        "bull_put_spread": {
            "profit_target_pct": 0.50, "stop_loss_mult": 2.0,
            "min_dte_exit": 7, "assignment_dte": 2,
            "no_assignment": True,
        },
    },
    "ledger": {
        "max_loss_pct": 0.02, "heat_cap_pct": 0.35,
        "fee_per_contract": 0.65,
    },
    "vol": {
        "hv_short": 20, "hv_long": 60,
        "ivr_sell": 50, "ivr_stand_down": 25,
        "min_iv_history": 30,
    },
}


def _parse_scalar(tok, lineno):
    low = tok.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    raise ValueError(f"gates.yaml line {lineno}: unsupported value {tok!r}")


def parse(text):
    """Parse the supported YAML subset into nested dicts."""
    root = {}
    stack = [(-1, root)]  # (indent_level, dict)
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if "\t" in line:
            raise ValueError(f"gates.yaml line {lineno}: tabs not allowed")
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2:
            raise ValueError(f"gates.yaml line {lineno}: indent must be 2-space")
        level = indent // 2
        content = line.strip()
        if ":" not in content:
            raise ValueError(f"gates.yaml line {lineno}: expected 'key: value'")
        key, _, val = content.partition(":")
        key, val = key.strip(), val.strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        if not val:
            child = {}
            parent[key] = child
            stack.append((level, child))
        else:
            parent[key] = _parse_scalar(val, lineno)
    return root


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_cache = {}


def load(path=None):
    """Load gates, deep-merged over DEFAULTS. Cached per path."""
    path = path or os.environ.get("GATES_CONFIG") or DEFAULT_PATH
    if path in _cache:
        return _cache[path]
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path) as f:
            cfg = _deep_merge(DEFAULTS, parse(f.read()))
    else:
        cfg = {s: dict(d) for s, d in DEFAULTS.items()}
    _cache[path] = cfg
    return cfg


def get(section, key, default=None, path=None):
    return load(path).get(section, {}).get(key, default)
