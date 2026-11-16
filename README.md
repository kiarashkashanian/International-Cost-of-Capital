# International Cost of Capital App

A Streamlit class project comparing the cost of equity, cost of debt, and WACC in USD and a selected foreign currency.

## Included files
- `app.py` — Streamlit dashboard, source retrieval, calculations, overrides, comparison, and downloads.
- `requirements.txt` — Python dependencies.
- `verification.xlsx` — independent sample calculation and assignment invariance checks.

## Financial methodology
The app uses the following domestic USD equity-cost baseline:

\[
R_{e,USD}=R_{f,USD}+\beta_U ERP
\]

It then applies the professor-provided international adjustment:

\[
1+R_{e,foreign}=(1+R_{e,USD})\frac{1+R_{f,foreign}}{1+R_{f,USD}}
\]

Debt costs:

\[
R_{d,USD}=R_{f,USD}+Spread_{BBB,USD}
\]
\[
R_{d,foreign}=R_{f,foreign}+Spread_{BBB,foreign}
\]

WACC:

\[
WACC=(1-d)R_e+dR_d(1-\tau)
\]

The foreign BBB spread defaults to the USD BBB spread. The user can switch on a foreign spread override. The selected project tax rate and debt share are applied consistently to both currency calculations.

**Important:** The domestic USD equity-cost baseline above is an explicit implementation assumption based on the supplied unlevered beta and ERP. Confirm it against the CAPM formula taught in class before submitting. Do not silently replace it with a relevered-beta model.

## Data sources
- Damodaran U.S. industry betas: https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls
- Damodaran ratings/default spreads: https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html
- OECD statutory corporate income tax rates: https://www.oecd.org/en/data/datasets/corporate-income-tax-rates-database.html
- Trading Economics 10-year government yields: https://tradingeconomics.com/country-list/government-bond-10y

The app attempts to retrieve data when opened and caches it for 24 hours. Use **Refresh source data** to force a new retrieval. Source pages can change their HTML or restrict automated access. If a source cannot be parsed, the app keeps the manual input fields available and displays a warning. Always inspect the source date/reference period shown by the provider.

## Run locally
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload `app.py`, `requirements.txt`, `README.md`, and `verification.xlsx`.
3. Sign in to https://share.streamlit.io/ using your GitHub account.
4. Choose **New app**, select the repository and branch, and set the main file path to `app.py`.
5. Deploy and test the public app URL.

## Required verification
The app includes code assertions for:
1. Equal government yields and equal spreads produce equal USD and foreign results.
2. Zero debt makes WACC equal cost of equity.
3. Changing only the foreign BBB spread does not change USD cost of debt or USD WACC.

Also complete the independent spreadsheet example in `verification.xlsx`. Record your own calculator/spreadsheet check in the course submission.