"""Frozen index universes (constituents as of 2026-10-11).

Sources (Wikipedia, retrieved 2026-10-11):
- S&P 500:  https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
- S&P 100:  https://en.wikipedia.org/wiki/S%26P_100
- Nasdaq-100: https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies
- Dow Jones Industrial Average:
  https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies

Symbol normalization for the Public.com API (verified 2026-10-11 via
get_quotes): uppercase, whitespace stripped, dots KEPT for class shares
("BRK.B", "BF.B" resolve; the dashed "BRK-B" form does NOT resolve).
Warrants/units excluded; lists deduped preserving Wikipedia order.
"""

from __future__ import annotations


def _dedupe(symbols):
    seen = set()
    out = []
    for s in symbols:
        s = s.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


SP500 = _dedupe([
    # A-B
    "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
    "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL",
    "GOOGL", "GOOG", "MO", "AMZN", "AMCR", "AEE", "AEP", "AXP", "AIG",
    "AMT", "AWK", "AMP", "AME", "AMGN", "APH", "ADI", "AON", "APA", "APO",
    "AAPL", "AMAT", "APP", "APTV", "ACGL", "ADM", "ARES", "ANET", "AJG",
    "AIZ", "T", "ATO", "ADSK", "ADP", "AZO", "AVY", "AXON", "BKR", "BALL",
    "BAC", "BAX", "BDX", "BRK.B", "BBY", "TECH", "BIIB", "BLK", "BX",
    "XYZ", "BE", "BNY", "BA", "BKNG", "BSX", "BMY", "AVGO", "BR", "BRO",
    "BF.B", "BG", "BXP", "CHRW", "CDNS", "CPT", "COF", "CAH", "CCL",
    "CARR", "CVNA", "CASY", "CAT", "CBOE", "CBRE", "CDW", "COR", "CNC",
    "CNP", "CF", "CRL", "SCHW", "CHTR", "CVX", "CMG", "CB", "CHD", "CIEN",
    "CI", "CINF", "CTAS", "CSCO", "C", "CFG",
    # C-H
    "CLX", "CME", "CMS", "KO", "CTSH", "COHR", "COIN", "CL", "CMCSA",
    "FIX", "COP", "ED", "STZ", "CEG", "COO", "CPRT", "GLW", "CPAY",
    "CSGP", "COST", "CRH", "CRWD", "CCI", "CSX", "CMI", "CVS", "DHR",
    "DRI", "DDOG", "DVA", "DECK", "DE", "DELL", "DAL", "DVN", "DXCM",
    "FANG", "DLR", "DG", "DLTR", "D", "DPZ", "DASH", "DOV", "DOW", "DHI",
    "DTE", "DUK", "DD", "ETN", "EBAY", "ECHO", "ECL", "EIX", "EW", "ELV",
    "EME", "EMR", "ETR", "EOG", "EQT", "EFX", "EQIX", "ERIE", "ESS", "EL",
    "EG", "EVRG", "P", "ES", "EXC", "EXE", "EXPE", "EXPD", "EXR", "XOM",
    "FFIV", "FDS", "FICO", "FAST", "FRT", "FDX", "FDXF", "FERG", "FIS",
    "FITB", "FSLR", "FE", "FISV", "FLEX", "F", "FTNT", "FTV", "FOXA",
    "FOX", "BEN", "FCX", "GRMN", "IT", "GE", "GEHC", "GEV", "GEN",
    "GNRC", "GD", "GIS", "GM", "GPC", "GILD", "GPN", "GL", "GDDY", "GS",
    "HAL", "HIG", "HAS", "HCA",
    # H-N
    "DOC", "HSIC", "HSY", "HPE", "HLT", "HD", "HONA", "HON", "HRL", "HST",
    "HWM", "HPQ", "HUBB", "HUM", "HBAN", "HII", "IBM", "IEX", "IDXX",
    "ITW", "ILMN", "INCY", "IR", "PODD", "INTC", "IBKR", "ICE", "IFF",
    "IP", "INTU", "ISRG", "IVZ", "INVH", "IQV", "IRM", "JBHT", "JBL",
    "JKHY", "J", "JNJ", "JCI", "JPM", "KVUE", "KDP", "KEY", "KEYS", "KMB",
    "KIM", "KMI", "KKR", "KLAC", "KHC", "KR", "LHX", "LH", "LRCX", "LVS",
    "LDOS", "LEN", "LII", "LLY", "LIN", "LYV", "LMT", "L", "LOW", "LULU",
    "LITE", "LYB", "MTB", "MPC", "MAR", "MRSH", "MLM", "MRVL", "MAS",
    "MA", "MKC", "MCD", "MCK", "MDT", "MRK", "META", "MET", "MTD", "MGM",
    "MCHP", "MU", "MSFT", "MAA", "MRNA", "MDLZ", "MPWR", "MNST", "MCO",
    "MS", "MOS", "MSI", "MSCI", "NDAQ", "NTAP", "NFLX", "NEM", "NWSA",
    "NWS", "NEE", "NKE", "NI", "NDSN", "NSC", "NTRS", "NOC", "NCLH",
    # N-T
    "NRG", "NUE", "NVDA", "NVR", "NXPI", "ORLY", "OXY", "ODFL", "OMC",
    "ON", "OKE", "ORCL", "OTIS", "PCAR", "PKG", "PLTR", "PANW", "PH",
    "PAYX", "PYPL", "PNR", "PEP", "PFE", "PCG", "PM", "PSX", "PNW",
    "PNC", "PPG", "PPL", "PFG", "PG", "PGR", "PLD", "PRU", "PEG", "PTC",
    "PSA", "PHM", "PWR", "QCOM", "DGX", "Q", "RL", "RJF", "RDDT", "RTX",
    "O", "REG", "REGN", "RF", "RSG", "RMD", "RVTY", "HOOD", "ROK", "ROL",
    "ROP", "ROST", "RCL", "SPGI", "CRM", "SNDK", "SBAC", "SLB", "STX",
    "SRE", "NOW", "SHW", "SPG", "SKYD", "SWKS", "SJM", "SW", "SNA",
    "SOLV", "SO", "LUV", "SWK", "SBUX", "STT", "STLD", "STE", "SYK",
    "SMCI", "SYF", "SNPS", "SYY", "TMUS", "TROW", "TTWO", "TPR", "TRGP",
    "TGT", "TEL", "TDY", "TER", "TSLA", "TXN", "TPL", "TXT", "TMO",
    "TJX", "TKO", "TSCO", "TT", "TDG", "TRV", "TRMB", "TFC", "TWLO",
    "TYL", "TSN",
    # U-Z
    "USB", "UBER", "UDR", "ULTA", "UNP", "UAL", "UPS", "URI", "UNH",
    "UHS", "VLO", "VEEV", "VTR", "VLTO", "VRSN", "VRSK", "VZ", "VRTX",
    "VRT", "VTRS", "VICI", "V", "VST", "VMRK", "VMC", "VYLR", "WRB",
    "GWW", "WAB", "WMT", "DIS", "WM", "WAT", "WEC", "WFC", "WELL", "WST",
    "WDC", "WY", "WSM", "WMB", "WTW", "WDAY", "WYNN", "XEL", "XYL",
    "YUM", "ZBRA", "ZBH", "ZTS",
])

SP100 = _dedupe([
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AMAT", "AMD", "AMGN", "AMT",
    "AMZN", "ANET", "AVGO", "AXP", "BA", "BAC", "BKNG", "BLK", "BMY",
    "BNY", "BRK.B", "C", "CAT", "CMCSA", "COF", "COP", "COST", "CRM",
    "CSCO", "CVS", "CVX", "DE", "DELL", "DHR", "DIS", "DUK", "EMR",
    "FDX", "GD", "GE", "GEV", "GILD", "GM", "GOOG", "GOOGL", "GS", "HD",
    "IBM", "INTC", "INTU", "ISRG", "JNJ", "JPM", "KO", "LIN", "LLY",
    "LMT", "LOW", "LRCX", "MA", "MCD", "MDLZ", "MDT", "META", "MMM",
    "MO", "MRK", "MS", "MSFT", "MU", "NEE", "NFLX", "NOW", "NVDA",
    "ORCL", "PANW", "PEP", "PFE", "PG", "PLTR", "PM", "QCOM", "RTX",
    "SBUX", "SCHW", "SNDK", "SO", "T", "TMO", "TMUS", "TSLA", "TXN",
    "UBER", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM",
])

NASDAQ100 = _dedupe([
    "ADBE", "AMD", "ABNB", "ALNY", "GOOGL", "GOOG", "AMZN", "AEP",
    "AMGN", "ADI", "AAPL", "AMAT", "APP", "ARM", "ASML", "ALAB", "ADSK",
    "ADP", "AXON", "BKR", "BKNG", "AVGO", "CDNS", "CTAS", "CSCO",
    "CCEP", "CMCSA", "CEG", "CPRT", "CRWV", "COST", "CRWD", "CSX",
    "DDOG", "DXCM", "FANG", "DASH", "EXC", "FAST", "FER", "FTNT",
    "GEHC", "GILD", "HONA", "HON", "IDXX", "INTC", "INTU", "ISRG",
    "KDP", "KLAC", "LRCX", "LIN", "LITE", "MAR", "MRVL", "MELI",
    "META", "MCHP", "MU", "MSFT", "MSTR", "MRNA", "MDLZ", "MPWR",
    "MNST", "NBIS", "NFLX", "NVDA", "NXPI", "ORLY", "ODFL", "PCAR",
    "PLTR", "PANW", "PAYX", "PYPL", "PDD", "PEP", "QCOM", "REGN",
    "RKLB", "ROP", "ROST", "SNDK", "STX", "SHOP", "SPCX", "SBUX",
    "SNPS", "TMUS", "TTWO", "TER", "TSLA", "TXN", "TRI", "VRTX",
    "WMT", "WDC", "WDAY", "XEL",
])

DOW30 = _dedupe([
    "MMM", "GOOGL", "AXP", "AMGN", "AMZN", "AAPL", "BA", "CAT", "CVX",
    "CSCO", "KO", "DIS", "GS", "HD", "HON", "IBM", "JNJ", "JPM", "MCD",
    "MRK", "MSFT", "NKE", "NVDA", "PG", "CRM", "SHW", "TRV", "UNH",
    "V", "WMT",
])

UNIVERSES = {
    "sp500": SP500,
    "sp100": SP100,
    "nasdaq100": NASDAQ100,
    "dow30": DOW30,
}


def list_universes():
    """Return {universe_name: constituent_count}."""
    return {k: len(v) for k, v in UNIVERSES.items()}


if __name__ == "__main__":
    for name, count in list_universes().items():
        print(f"{name}: {count}")


# ---- Live universe files (universes/*.txt, refreshed by build_universes.py) ----
# Prefer the text files when present; fall back to the embedded frozen lists.
def _load_universe_file(name):
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "universes", f"{name}.txt")
    if not os.path.exists(path):
        return None
    syms = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            syms.append(line.upper())
    return _dedupe(syms) or None


for _name in list(UNIVERSES):
    _loaded = _load_universe_file(_name)
    if _loaded:
        UNIVERSES[_name] = _loaded
# russell2000 has no embedded list; add it when the file exists
_r2k = _load_universe_file("russell2000")
if _r2k:
    UNIVERSES["russell2000"] = _r2k
del _name, _loaded, _r2k
