# qsif funds vs Nifty 50

Daily % change (bars) and cumulative return (lines) of each fund against Nifty 50 for the
last 15 common sessions. Updated automatically by GitHub Actions on weekday mornings.

### qsif Equity Long-Short (Direct)
![qsif Equity Long-Short](charts/qsif_equity_long_short.png)

### qsif Equity Ex-Top 100 Long-Short (Direct)
![qsif Equity Ex-Top 100 Long-Short](charts/qsif_equity_ex_top_100_long_short.png)

### qsif Hybrid Long-Short (Direct)
![qsif Hybrid Long-Short](charts/qsif_hybrid_long_short.png)

### qsif Sector Rotation Long-Short (Direct)
![qsif Sector Rotation Long-Short](charts/qsif_sector_rotation_long_short.png)

- Fund NAVs: free Charlie API (`/v1/sif/hnav/{ISIN}`)
- Nifty 50 closes: yfinance (`^NSEI`)
- Data tables: the `.csv` files in [`charts/`](charts/)
- Add or change funds: edit the `SCHEMES` list at the top of `sif_vs_nifty.py`
- Run manually: Actions tab > "Daily SIF vs Nifty charts" > Run workflow
- Run locally: `pip install -r requirements.txt && python sif_vs_nifty.py`

Only dates present in both series are used, so each bar compares the same session-to-session move.
For education and research, not investment advice.
