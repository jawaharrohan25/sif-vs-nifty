# SIF funds vs Nifty 50

Daily % change (bars) and cumulative return (lines) of each fund against Nifty 50 for the
last 15 common sessions. Updated automatically by GitHub Actions on weekday mornings.

### qsif Equity Long Short Fund (Direct)
![qsif Equity Long Short Fund (Direct)](charts/sif_1.png)

### qsif Hybrid Long-Short Fund (Direct)
![qsif Hybrid Long-Short Fund (Direct)](charts/sif_5.png)

### qsif Active Asset Allocator Long-Short Fund (Direct)
![qsif Active Asset Allocator Long-Short Fund (Direct)](charts/sif_90.png)

### qsif Equity Ex-Top 100 Long-Short Fund (Direct)
![qsif Equity Ex-Top 100 Long-Short Fund (Direct)](charts/sif_23.png)

- Fund NAVs: free Charlie API (`/v1/sif/hnav/{code}`)
- Nifty 50 closes: yfinance (`^NSEI`)
- Data tables: the `.csv` files in [`charts/`](charts/)
- Add or change funds: edit the `SCHEMES` list at the top of `sif_vs_nifty.py`
- This file is regenerated on every run

Only dates present in both series are used, so each bar compares the same session-to-session move.
For education and research, not investment advice.
