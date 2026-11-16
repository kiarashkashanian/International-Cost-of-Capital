import io
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="International Cost of Capital", page_icon="📊", layout="wide")

BETA_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
BETA_PAGE = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"
OECD_URL = "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html"
OECD_LATEST_URL = "https://www.oecd.org/en/publications/corporate-tax-statistics-2026_73af6222-en/full-report/statutory-corporate-income-tax-rates_ce84abb9.html"
TE_COUNTRY_LIST = "https://tradingeconomics.com/country-list/government-bond-10y"
TE_BONDS = "https://tradingeconomics.com/bonds"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CostOfCapitalClassProject/1.0)"}
DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_SPREAD = 0.0111  # Damodaran Baa2/BBB large non-financial service firms; updated from source on refresh.
DEFAULT_TAX = {"United States": 0.257}
DEFAULT_YIELDS = {"United States": 0.0435}

def pct(x):
    return f"{x:.2%}"

def clean_num(value):
    if pd.isna(value):
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None

def fetch_excel_betas():
    r = requests.get(BETA_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    xls = pd.ExcelFile(io.BytesIO(r.content))
    df = pd.read_excel(xls, sheet_name=0, header=None)
    header_idx = None
    for i in range(min(15, len(df))):
        row = " ".join(str(v).lower() for v in df.iloc[i].tolist() if pd.notna(v))
        if "industry name" in row and "unlevered beta" in row:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not identify the industry/unlevered beta columns in Damodaran's workbook.")
    out = pd.read_excel(io.BytesIO(r.content), sheet_name=0, header=header_idx)
    out.columns = [str(c).strip() for c in out.columns]
    industry_col = next((c for c in out.columns if "industry name" in c.lower()), None)
    beta_col = next((c for c in out.columns if "unlevered beta" in c.lower() and "corrected" not in c.lower()), None)
    if not industry_col or not beta_col:
        raise ValueError("Damodaran workbook columns changed; use the manual beta override.")
    result = out[[industry_col, beta_col]].copy()
    result.columns = ["Industry", "Unlevered beta"]
    result["Unlevered beta"] = pd.to_numeric(result["Unlevered beta"], errors="coerce")
    result = result.dropna(subset=["Industry", "Unlevered beta"])
    result = result[result["Industry"].astype(str).str.strip().ne("")]
    result["Industry"] = result["Industry"].astype(str).str.strip()
    return result.drop_duplicates("Industry"), datetime.now(timezone.utc).date().isoformat()

def fetch_bbb_spread():
    tables = pd.read_html(requests.get(RATINGS_URL, headers=HEADERS, timeout=30).text)
    for t in tables:
        flat = " ".join(str(c).lower() for c in t.columns)
        body = " ".join(t.astype(str).fillna("").values.flatten()).lower()
        if "baa2" in body and "spread" in body:
            # Target source table: large non-financial service firms, Baa2/BBB = 1.11% in Jan 2026.
            # Find the Baa2/BBB row and use its Spread column where available.
            for _, row in t.iterrows():
                vals = [str(v).strip() for v in row.tolist()]
                if any("Baa2/BBB" in v or "Baa2" in v and "BBB" in v for v in vals):
                    nums = [clean_num(v) for v in vals]
                    nums = [n for n in nums if n is not None]
                    if nums:
                        # Source table expresses spread in percentage points.
                        return nums[-1] / 100.0, "Damodaran ratings table (large non-financial service firms)"
    # Source's current published Baa2/BBB value; clearly identified and date-stamped by source page.
    return DEFAULT_SPREAD, "Damodaran ratings page fallback (Baa2/BBB, large non-financial service firms)"

def fetch_oecd_tax_table():
    errors = []
    for url in (OECD_LATEST_URL, OECD_URL):
        try:
            html = requests.get(url, headers=HEADERS, timeout=30).text
            tables = pd.read_html(html)
            candidates = []
            for t in tables:
                joined = " ".join(str(x).lower() for x in t.columns) + " " + " ".join(t.astype(str).fillna("").values.flatten()).lower()
                if "country" in joined and ("combined" in joined or "statutory" in joined):
                    candidates.append(t)
            if candidates:
                t = max(candidates, key=len).copy()
                # Flexible parsing of the published country table.
                t.columns = [str(c).strip() for c in t.columns]
                country_col = next((c for c in t.columns if "country" in c.lower() or "jurisdiction" in c.lower()), t.columns[0])
                rate_col = next((c for c in t.columns if "combined" in c.lower() or "statutory" in c.lower()), None)
                if rate_col is None:
                    # Some OECD tables have unnamed columns; choose first mostly numeric column after country.
                    possible = [c for c in t.columns if c != country_col]
                    rate_col = possible[0] if possible else None
                if rate_col:
                    out = t[[country_col, rate_col]].copy()
                    out.columns = ["Country", "Tax rate (%)"]
                    out["Tax rate (%)"] = out["Tax rate (%)"].map(clean_num)
                    out = out.dropna(subset=["Tax rate (%)"])
                    out["Country"] = out["Country"].astype(str).str.replace(r"\s*\([A-Z]{3}\)\s*", "", regex=True).str.strip()
                    out["Tax rate"] = out["Tax rate (%)"] / 100
                    return out[["Country", "Tax rate"]].drop_duplicates("Country"), url
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError("OECD tax table could not be parsed automatically. " + " | ".join(errors[-1:]))

def fetch_te_yields():
    html = requests.get(TE_COUNTRY_LIST, headers=HEADERS, timeout=30).text
    tables = pd.read_html(html)
    for t in tables:
        cols = [str(c).lower() for c in t.columns]
        if any("country" in c for c in cols) and any("last" in c for c in cols):
            country_col = next(c for c in t.columns if "country" in str(c).lower())
            last_col = next(c for c in t.columns if "last" in str(c).lower())
            ref_col = next((c for c in t.columns if "reference" in str(c).lower()), None)
            out = t[[country_col, last_col] + ([ref_col] if ref_col else [])].copy()
            out.columns = ["Country", "Yield (%)"] + (["Reference"] if ref_col else [])
            out["Yield (%)"] = out["Yield (%)"].map(clean_num)
            out = out.dropna(subset=["Yield (%)"])
            out["Yield"] = out["Yield (%)"] / 100
            return out, datetime.now(timezone.utc).date().isoformat()
    raise RuntimeError("Trading Economics country-list table structure changed.")

def fetch_all():
    status = {}
    beta_df, beta_date = fetch_excel_betas()
    status["beta"] = {"source": BETA_PAGE, "retrieved": beta_date, "observation": "Damodaran date shown on source page"}
    spread, spread_source = fetch_bbb_spread()
    status["spread"] = {"source": RATINGS_URL, "retrieved": datetime.now(timezone.utc).date().isoformat(), "note": spread_source}
    tax_df, tax_source = fetch_oecd_tax_table()
    status["tax"] = {"source": tax_source, "retrieved": datetime.now(timezone.utc).date().isoformat()}
    yield_df, yield_date = fetch_te_yields()
    status["yields"] = {"source": TE_COUNTRY_LIST, "retrieved": yield_date, "note": "Trading Economics reference period is shown in the table"}
    return beta_df, spread, tax_df, yield_df, status

def calc_costs(beta, erp, rf_us, rf_foreign, spread_usd, spread_foreign, tax, debt_share):
    # Class project baseline domestic equity cost: unlevered CAPM using the supplied unlevered beta.
    re_usd = rf_us + beta * erp
    # Professor-provided international conversion formula:
    re_foreign = (1 + re_usd) * (1 + rf_foreign) / (1 + rf_us) - 1
    rd_usd = rf_us + spread_usd
    rd_foreign = rf_foreign + spread_foreign
    wacc_usd = (1 - debt_share) * re_usd + debt_share * rd_usd * (1 - tax)
    wacc_foreign = (1 - debt_share) * re_foreign + debt_share * rd_foreign * (1 - tax)
    return {
        "USD cost of equity": re_usd, "Foreign cost of equity": re_foreign,
        "USD cost of debt": rd_usd, "Foreign cost of debt": rd_foreign,
        "USD WACC": wacc_usd, "Foreign WACC": wacc_foreign,
    }

def run_checks():
    # Deterministic tests for the assignment's required invariants.
    p = dict(beta=0.9, erp=0.065, rf_us=0.04, rf_foreign=0.04,
             spread_usd=0.0111, spread_foreign=0.0111, tax=0.25, debt_share=0.30)
    a = calc_costs(**p)
    assert abs(a["USD cost of equity"] - a["Foreign cost of equity"]) < 1e-12
    assert abs(a["USD cost of debt"] - a["Foreign cost of debt"]) < 1e-12
    assert abs(a["USD WACC"] - a["Foreign WACC"]) < 1e-12
    p0 = dict(p, debt_share=0.0)
    z = calc_costs(**p0)
    assert abs(z["USD WACC"] - z["USD cost of equity"]) < 1e-12
    assert abs(z["Foreign WACC"] - z["Foreign cost of equity"]) < 1e-12
    p1 = dict(p, spread_foreign=0.03)
    o = calc_costs(**p1)
    assert abs(o["USD WACC"] - a["USD WACC"]) < 1e-12
    assert abs(o["USD cost of debt"] - a["USD cost of debt"]) < 1e-12
    return True

@st.cache_data(ttl=86400, show_spinner=False)
def cached_fetch():
    return fetch_all()

st.title("🌐 International Cost of Capital")
st.caption("Compare USD and selected-country costs of equity, debt, and WACC using class-provided formulas.")

if "data" not in st.session_state:
    st.session_state["data"] = None
if "fetch_error" not in st.session_state:
    st.session_state["fetch_error"] = None

top1, top2 = st.columns([1, 4])
with top1:
    if st.button("🔄 Refresh source data", use_container_width=True):
        cached_fetch.clear()
        st.session_state["data"] = None
        st.session_state["fetch_error"] = None
with top2:
    st.caption("Source data are cached for 24 hours. Refresh retrieves the latest available observations.")

if st.session_state["data"] is None:
    try:
        with st.spinner("Retrieving Damodaran, OECD, and Trading Economics data..."):
            st.session_state["data"] = cached_fetch()
    except Exception as e:
        st.session_state["fetch_error"] = str(e)

data = st.session_state["data"]
if data:
    beta_df, auto_spread, tax_df, yield_df, source_status = data
else:
    st.warning("One or more live sources could not be parsed. Manual inputs remain available. Check the source status and enter missing values below.")
    st.caption(st.session_state["fetch_error"] or "No live data loaded.")
    beta_df = pd.DataFrame({"Industry": [DEFAULT_INDUSTRY], "Unlevered beta": [0.90]})
    auto_spread = DEFAULT_SPREAD
    tax_df = pd.DataFrame({"Country": ["United States"], "Tax rate": [0.257]})
    yield_df = pd.DataFrame({"Country": ["United States"], "Yield": [0.0435], "Reference": ["Fallback estimate"]})
    source_status = {}

# Normalize lookup frames
tax_map = dict(zip(tax_df["Country"], tax_df["Tax rate"]))
yield_map = dict(zip(yield_df["Country"], yield_df["Yield"]))
industries = sorted(beta_df["Industry"].dropna().astype(str).unique().tolist())
if not industries:
    industries = [DEFAULT_INDUSTRY]
countries = sorted(set(tax_map) | set(yield_map) | {"United States"})
if "United States" not in countries:
    countries.insert(0, "United States")

with st.sidebar:
    st.header("Project assumptions")
    industry_default = industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0
    industry = st.selectbox("Industry", industries, index=industry_default)
    country_default = countries.index("United States")
    country = st.selectbox("Target country", countries, index=country_default)
    erp_pct = st.number_input("Equity risk premium (%)", min_value=0.0, max_value=30.0, value=6.5, step=0.1)
    debt_pct = st.number_input("Target debt share (%)", min_value=0.0, max_value=100.0, value=30.0, step=1.0)
    tax_choice = st.radio("Project tax rate", ["U.S. corporate tax rate", "Selected-country corporate tax rate"], index=0)
    use_foreign_spread = st.toggle("Override foreign BBB spread", value=False)

beta_auto_row = beta_df[beta_df["Industry"] == industry]
beta_auto = float(beta_auto_row.iloc[0]["Unlevered beta"]) if len(beta_auto_row) else 0.90
us_tax_auto = float(tax_map.get("United States", 0.257))
foreign_tax_auto = float(tax_map.get(country, us_tax_auto))
us_yield_auto = float(yield_map.get("United States", 0.0435))
foreign_yield_auto = float(yield_map.get(country, us_yield_auto))

st.subheader("Data inputs and manual overrides")
c1, c2, c3 = st.columns(3)
with c1:
    beta = st.number_input("Unlevered industry beta", value=float(beta_auto), min_value=0.0, max_value=5.0, step=0.01, format="%.3f")
    tax_us = st.number_input("U.S. corporate tax rate (%)", value=us_tax_auto*100, min_value=0.0, max_value=60.0, step=0.1)/100
with c2:
    tax_foreign = st.number_input(f"{country} corporate tax rate (%)", value=foreign_tax_auto*100, min_value=0.0, max_value=60.0, step=0.1)/100
    spread_usd = st.number_input("USD BBB borrowing spread (%)", value=float(auto_spread*100), min_value=0.0, max_value=30.0, step=0.01)/100
with c3:
    rf_us = st.number_input("U.S. 10-year government yield (%)", value=us_yield_auto*100, min_value=-5.0, max_value=50.0, step=0.01)/100
    rf_foreign = st.number_input(f"{country} 10-year government yield (%)", value=foreign_yield_auto*100, min_value=-5.0, max_value=50.0, step=0.01)/100

if use_foreign_spread:
    spread_foreign = st.number_input(f"{country} BBB spread override (%)", value=float(auto_spread*100), min_value=0.0, max_value=30.0, step=0.01)/100
else:
    spread_foreign = spread_usd
    st.info(f"Foreign BBB spread is linked to the USD BBB spread ({pct(spread_usd)}). Turn on the override to enter a different spread.")

tax = tax_us if tax_choice.startswith("U.S.") else tax_foreign
debt_share = debt_pct/100
results = calc_costs(beta, erp_pct/100, rf_us, rf_foreign, spread_usd, spread_foreign, tax, debt_share)

st.subheader("Results: USD vs. foreign currency")
st.caption(f"Selected industry: {industry} · Target country: {country} · Tax rate used in both WACCs: {pct(tax)} · Debt share: {pct(debt_share)}")
left, right = st.columns(2)
with left:
    st.markdown("### 🇺🇸 USD")
    st.metric("Cost of equity", pct(results["USD cost of equity"]))
    st.metric("Cost of debt (pre-tax)", pct(results["USD cost of debt"]))
    st.metric("WACC", pct(results["USD WACC"]))
with right:
    st.markdown(f"### 🌍 {country}")
    st.metric("Cost of equity", pct(results["Foreign cost of equity"]))
    st.metric("Cost of debt (pre-tax)", pct(results["Foreign cost of debt"]))
    st.metric("WACC", pct(results["Foreign WACC"]))

with st.expander("Calculation details and assumptions", expanded=True):
    st.latex(r"R_{e,USD}=R_{f,USD}+\beta_U\times ERP")
    st.latex(r"1+R_{e,foreign}=(1+R_{e,USD})\times\frac{1+R_{f,foreign}}{1+R_{f,USD}}")
    st.latex(r"R_d=R_f+BBB\ spread")
    st.latex(r"WACC=(1-d)R_e+dR_d(1-\tau)")
    st.write("The domestic USD equity cost uses an unlevered CAPM baseline because the assignment supplies unlevered beta and the international conversion equation. Confirm this domestic CAPM baseline against your course notes.")
    st.write("The same selected project tax rate, debt share, and equity risk premium are used for both currency calculations. The foreign cost of equity is converted using the professor-provided gross risk-free-rate ratio.")
    st.write("The foreign BBB spread defaults to the USD BBB spread. A manual foreign spread override affects only foreign debt cost and foreign WACC.")

st.subheader("All-industry comparison")
rows = []
for _, r in beta_df.iterrows():
    b = float(r["Unlevered beta"])
    vals = calc_costs(b, erp_pct/100, rf_us, rf_foreign, spread_usd, spread_foreign, tax, debt_share)
    rows.append({"Industry": r["Industry"], "Unlevered beta": b, **vals})
industry_results = pd.DataFrame(rows).sort_values("USD WACC", ascending=False)
st.dataframe(industry_results.style.format({c: "{:.2%}" for c in industry_results.columns if c != "Industry" and c != "Unlevered beta"}).format({"Unlevered beta": "{:.3f}"}), use_container_width=True, height=420)

# Data provenance
st.subheader("Sources and data dates")
source_rows = [
    {"Input": "Industry unlevered beta", "Source": BETA_PAGE, "Retrieved": source_status.get("beta", {}).get("retrieved", "Fallback/manual"), "Observation date": "See Damodaran page"},
    {"Input": "BBB borrowing spread", "Source": RATINGS_URL, "Retrieved": source_status.get("spread", {}).get("retrieved", "Fallback/manual"), "Observation date": "See Damodaran page"},
    {"Input": "Corporate tax rates", "Source": source_status.get("tax", {}).get("source", OECD_URL), "Retrieved": source_status.get("tax", {}).get("retrieved", "Fallback/manual"), "Observation date": "OECD edition/year shown on source"},
    {"Input": "10-year government yields", "Source": TE_COUNTRY_LIST, "Retrieved": source_status.get("yields", {}).get("retrieved", "Fallback/manual"), "Observation date": "Trading Economics Reference column"},
]
st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)
st.markdown(f"- [Damodaran industry betas]({BETA_PAGE}) · [Damodaran ratings/spreads]({RATINGS_URL}) · [OECD corporate tax rates]({OECD_LATEST_URL}) · [Trading Economics bond yields]({TE_BONDS})")

# Downloads
st.subheader("Download results")
assumptions = pd.DataFrame([{
    "Industry": industry, "Target country": country, "ERP": erp_pct/100, "Debt share": debt_share,
    "Tax choice": tax_choice, "Tax rate used": tax, "Unlevered beta": beta,
    "U.S. 10Y yield": rf_us, "Foreign 10Y yield": rf_foreign,
    "USD BBB spread": spread_usd, "Foreign BBB spread": spread_foreign,
    "Foreign spread override": use_foreign_spread,
}])
main_results = pd.DataFrame([results])
csv_bytes = pd.concat([assumptions, main_results], axis=1).to_csv(index=False).encode("utf-8")
st.download_button("Download selected-case CSV", csv_bytes, file_name="international_cost_of_capital_results.csv", mime="text/csv")

excel_buffer = io.BytesIO()
with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
    assumptions.to_excel(writer, sheet_name="Assumptions", index=False)
    main_results.to_excel(writer, sheet_name="Selected Results", index=False)
    industry_results.to_excel(writer, sheet_name="All Industries", index=False)
    pd.DataFrame(source_rows).to_excel(writer, sheet_name="Sources", index=False)
st.download_button("Download results workbook (Excel)", excel_buffer.getvalue(), file_name="international_cost_of_capital_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.subheader("Built-in verification")
try:
    run_checks()
    st.success("All three required invariance checks passed: equal yields/equal spreads, zero debt, and foreign spread override isolation.")
except AssertionError:
    st.error("A built-in calculation check failed. Review calc_costs() before relying on outputs.")

st.caption("Educational project tool, not investment advice. Verify source observations and course-specific formula conventions before submission.")