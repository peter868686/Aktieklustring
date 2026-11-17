"""
Hämtar rådata till aktieklusterprojektet och sparar den i data/raw/.

Källor (alla gratis, via API):
1. Nasdaq      – alla noterade aktier med sektor, bransch, land och börsvärde
2. SEC EDGAR   – bolagens räkenskaper (omsättning, resultat, tillgångar, skulder m.m.)
3. Yahoo Finance (via yfinance) – tre års dagliga kurser

Kör från projektets rotmapp:
    python src/fetch_data.py
"""

import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# Inställningar
# ---------------------------------------------------------------------------
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

MIN_MARKET_CAP = 300_000_000  # 300 miljoner dollar – gränsen mellan mikrobolag och småbolag
SEC_YEAR = 2025               # räkenskapsår (senaste helår som alla bolag har rapporterat)
PRICE_PERIOD = "3y"           # tre års kurshistorik
BATCH_SIZE = 200              # antal aktier per kursanrop

# SEC kräver att man anger vem man är (namn + e-post) i varje anrop.
# BYT till ditt eget namn och din e-post innan du kör skriptet!
SEC_HEADERS = {"User-Agent": "Ditt Namn din.epost@example.com"}

# Nasdaq nekar anrop som inte ser ut att komma från en webbläsare.
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}

# Räkenskapsposter från SEC: (taggnamn, period, kolumnnamn)
# "CY2025"    = flöde under kalenderåret (t.ex. omsättning, resultat)
# "CY2025Q4I" = värde vid årets slut (t.ex. tillgångar, skulder)
SEC_TAGS = [
    ("Revenues",                                              f"CY{SEC_YEAR}",    "revenue_a"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax",   f"CY{SEC_YEAR}",    "revenue_b"),
    ("NetIncomeLoss",                                         f"CY{SEC_YEAR}",    "net_income"),
    ("OperatingIncomeLoss",                                   f"CY{SEC_YEAR}",    "operating_income"),
    ("ResearchAndDevelopmentExpense",                         f"CY{SEC_YEAR}",    "rnd_expense"),
    ("Assets",                                                f"CY{SEC_YEAR}Q4I", "assets"),
    ("Liabilities",                                           f"CY{SEC_YEAR}Q4I", "liabilities"),
    ("StockholdersEquity",                                    f"CY{SEC_YEAR}Q4I", "equity"),
    ("CashAndCashEquivalentsAtCarryingValue",                 f"CY{SEC_YEAR}Q4I", "cash"),
]


def to_yahoo_ticker(symbol: str) -> str:
    """Nasdaq skriver t.ex. 'BRK/B', SEC och Yahoo skriver 'BRK-B'."""
    return symbol.strip().replace("/", "-").replace(".", "-").upper()


# ---------------------------------------------------------------------------
# 1. Nasdaq – listan över aktier
# ---------------------------------------------------------------------------
def fetch_nasdaq() -> pd.DataFrame:
    print("1/3 Hämtar aktielista från Nasdaq ...")
    url = "https://api.nasdaq.com/api/screener/stocks"
    r = requests.get(url, params={"tableonly": "true", "download": "true"},
                     headers=NASDAQ_HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"]["rows"])

    df["marketCap"] = pd.to_numeric(df["marketCap"], errors="coerce")
    df["ipoyear"] = pd.to_numeric(df["ipoyear"], errors="coerce")
    df["ticker"] = df["symbol"].apply(to_yahoo_ticker)
    df = df[["ticker", "name", "sector", "industry", "country", "ipoyear", "marketCap"]]

    df.to_csv(RAW_DIR / "nasdaq_aktier.csv", index=False)
    print(f"    {len(df)} aktier sparade i nasdaq_aktier.csv")
    return df


# ---------------------------------------------------------------------------
# 2. SEC EDGAR – räkenskaper
# ---------------------------------------------------------------------------
def fetch_sec() -> pd.DataFrame:
    print("2/3 Hämtar räkenskaper från SEC ...")

    # Koppling ticker -> CIK (SEC:s bolagsnummer)
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers=SEC_HEADERS, timeout=60)
    r.raise_for_status()
    mapping = pd.DataFrame(r.json().values()).rename(columns={"cik_str": "cik"})
    mapping["ticker"] = mapping["ticker"].apply(to_yahoo_ticker)
    df = mapping[["ticker", "cik"]].drop_duplicates("ticker")

    # En "frame" = ett nyckeltal för ALLA bolag ett visst år, i ett enda anrop
    for tag, period, col in SEC_TAGS:
        url = f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json"
        r = requests.get(url, headers=SEC_HEADERS, timeout=60)
        r.raise_for_status()
        frame = pd.DataFrame(r.json()["data"])[["cik", "val"]]
        frame = frame.drop_duplicates("cik").rename(columns={"val": col})
        df = df.merge(frame, on="cik", how="left")
        print(f"    {col}: {frame.shape[0]} bolag")
        time.sleep(0.2)  # SEC tillåter max 10 anrop/sekund

    # Bolag rapporterar omsättning under olika taggar – slå ihop dem
    df["revenue"] = df["revenue_a"].fillna(df["revenue_b"])
    df = df.drop(columns=["revenue_a", "revenue_b"])

    df.to_csv(RAW_DIR / "sec_rakenskaper.csv", index=False)
    print(f"    Sparade sec_rakenskaper.csv ({len(df)} tickers)")
    return df


# ---------------------------------------------------------------------------
# 3. Yahoo Finance – dagliga kurser
# ---------------------------------------------------------------------------
def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    print(f"3/3 Hämtar kurser för {len(tickers)} aktier från Yahoo Finance ...")
    tickers = tickers + ["SPY"]  # SPY = S&P 500-index, behövs för att räkna beta

    parts = []
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        data = yf.download(batch, period=PRICE_PERIOD, interval="1d",
                           auto_adjust=True, progress=False, threads=True)
        parts.append(data["Close"])  # justerad stängningskurs
        print(f"    {min(i + BATCH_SIZE, len(tickers))}/{len(tickers)} klara")
        time.sleep(1)  # liten paus så att Yahoo inte spärrar oss

    prices = pd.concat(parts, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]
    prices.to_csv(RAW_DIR / "kurser.csv")
    print(f"    Sparade kurser.csv ({prices.shape[0]} dagar x {prices.shape[1]} aktier)")
    return prices


# ---------------------------------------------------------------------------
def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    nasdaq = fetch_nasdaq()
    fetch_sec()

    # Kurser hämtas bara för aktier över gränsen för börsvärde (sparar tid)
    selected = nasdaq.loc[nasdaq["marketCap"] > MIN_MARKET_CAP, "ticker"].tolist()
    fetch_prices(selected)

    print("\nKlart! All rådata ligger i data/raw/")


if __name__ == "__main__":
    main()