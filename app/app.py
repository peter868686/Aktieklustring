"""
Streamlit-app: välj en aktie och se vilket kluster den tillhör
och vilka aktier som har betett sig mest likt.

Kör från projektets rotmapp:
    streamlit run app/app.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Aktier som liknar varandra", layout="wide")

# ---------------------------------------------------------------------------
# Inställningar och data
# ---------------------------------------------------------------------------
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "aktier_kluster.csv"

CLUSTER_INFO = {
    "Stabila storbolag": "Stora, lönsamma bolag vars aktier svänger lite och har haft små kursfall.",
    "Medelbolag": "Bolag nära genomsnittet i det mesta, men med svag kursutveckling de senaste tre åren.",
    "Högbeta-vinnare": "Aktier som har stigit kraftigt, men som svänger mycket mer än marknaden, åt båda hållen.",
    "Krisbolag": "Bolag med stora förluster, stora kursfall och negativ kursutveckling.",
    "Forskningsbolag": "Bolag som forskar mycket i förhållande till sin försäljning och ofta går med förlust.",
}

# De 8 nyckeltal som klustringen använde, med läsbara namn
FEATURE_LABELS = {
    "avkastning": "Avkastning per år",
    "volatilitet": "Volatilitet",
    "beta": "Beta",
    "max_fall": "Största fall",
    "vinstmarginal": "Vinstmarginal",
    "fou_andel": "FoU-andel",
    "vinstavkastning": "Vinstavkastning (E/P)",
    "log_borsvarde": "Storlek (log börsvärde)",
}
PERCENT = ["avkastning", "volatilitet", "max_fall", "vinstmarginal", "fou_andel", "vinstavkastning"]


@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    return df.sort_values("marketCap", ascending=False).reset_index(drop=True)


def fmt(col: str, value: float) -> str:
    """Visar procentnyckeltal som procent och övriga med två decimaler."""
    return f"{value:.0%}" if col in PERCENT else f"{value:.2f}"


df = load_data()
z_cols = [f"z_{c}" for c in FEATURE_LABELS]

# ---------------------------------------------------------------------------
# Rubrik och val av aktie
# ---------------------------------------------------------------------------
st.title("Hitta aktier som beter sig likt")
st.write(
    "Välj en aktie för att se vilket kluster den tillhör och vilka aktier som har betett sig "
    "mest likt de senaste tre åren. Klustringen bygger på kursbeteende och räkenskaper, "
    "inte på bransch, så liknande aktier kan komma från helt andra sektorer."
)
st.caption("⚠️ Historiskt beteende garanterar inte framtida beteende. Appen ger inga investeringsråd.")

labels = df["ticker"] + " – " + df["name"]
default = int(np.flatnonzero(df["ticker"] == "AAPL")[0]) if (df["ticker"] == "AAPL").any() else 0
choice = st.selectbox("Välj aktie (du kan skriva för att söka)", labels, index=default)
stock = df[labels == choice].iloc[0]

# ---------------------------------------------------------------------------
# Aktiens kluster och nyckeltal
# ---------------------------------------------------------------------------
st.subheader(f"{stock['name']} tillhör klustret: {stock['klustertyp']}")
st.write(CLUSTER_INFO[stock["klustertyp"]])
st.write(f"Sektor enligt Nasdaq: **{stock['sector']}**")

for column, col in zip(st.columns(4), ["avkastning", "volatilitet", "beta", "vinstmarginal"]):
    column.metric(FEATURE_LABELS[col], fmt(col, stock[col]))

# ---------------------------------------------------------------------------
# De 5 mest lika aktierna (kortast avstånd i de skalade nyckeltalen)
# ---------------------------------------------------------------------------
distance = np.sqrt(((df[z_cols] - stock[z_cols].astype(float)) ** 2).sum(axis=1))
similar = df.assign(avstand=distance).drop(index=stock.name).nsmallest(5, "avstand")

st.subheader("De 5 aktier som har betett sig mest likt")
other_sector = (similar["sector"] != stock["sector"]).sum()
st.write(f"{other_sector} av de 5 tillhör en annan sektor än {stock['ticker']}.")

table = similar[["ticker", "name", "sector", "klustertyp",
                 "avkastning", "volatilitet", "beta", "vinstmarginal"]].copy()
for col in ["avkastning", "volatilitet", "vinstmarginal"]:
    table[col] = table[col].map(lambda v: f"{v:.0%}")
table["beta"] = table["beta"].round(2)
table.columns = ["Ticker", "Namn", "Sektor", "Kluster",
                 "Avkastning/år", "Volatilitet", "Beta", "Vinstmarginal"]
st.dataframe(table, hide_index=True)

# ---------------------------------------------------------------------------
# Varför liknar de varandra?
# ---------------------------------------------------------------------------
st.subheader("Varför liknar de varandra?")
st.write(
    "Diagrammet visar hur den valda aktien och snittet av de 5 mest lika aktierna ligger till "
    "jämfört med genomsnittet för alla aktier (0). Åt höger betyder högre än genomsnittet, "
    "åt vänster lägre. Ju mer staplarna liknar varandra, desto mer likt har aktierna betett sig."
)
chart = pd.DataFrame({
    "Nyckeltal": list(FEATURE_LABELS.values()),
    stock["ticker"]: stock[z_cols].astype(float).values,
    "Snitt av de 5 mest lika": similar[z_cols].mean().values,
}).melt(id_vars="Nyckeltal", var_name="Aktie", value_name="Standardavvikelser från genomsnittet")

fig = px.bar(chart, x="Standardavvikelser från genomsnittet", y="Nyckeltal",
             color="Aktie", barmode="group", orientation="h")
st.plotly_chart(fig)