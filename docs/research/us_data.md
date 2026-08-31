# Free-Tier US Equities Data Sources for a Local Research System (verified August 26, 2026)

## Verification note
I live-checked pricing/docs pages for the sources below via direct fetch on 2026-08-26. Several vendor sites (SEC.gov, FMP, CBOE, Finnhub's JS-rendered docs) blocked or returned no usable body to the fetch tool in this session; for those I flag confidence level explicitly. One important, non-obvious finding: **Polygon.io's entire domain now 301-redirects to `massive.com`** (confirmed on both the marketing site and `/docs/...` paths) — this looks like a rebrand, not a shutdown, but treat as newly-discovered and re-verify before building against it.

---

## 1. OHLCV Price Data

| Source | What it gives | Free-tier limits | Key/registration | 2026 status |
|---|---|---|---|---|
| **yfinance** (unofficial Yahoo Finance wrapper) | Daily/intraday OHLCV, dividends/splits, options chains (`Ticker.options`, `Ticker.option_chain()`), earnings dates, basic fundamentals | No hard published quota — throttled by Yahoo's undocumented anti-bot limits; frequent 429s/curl-cffi impersonation needed | No key | **Verified actively maintained**: latest release v1.6.0, Aug 13 2026 (pypi.org/project/yfinance). Riskiest source long-term — it scrapes an unofficial endpoint and periodically breaks when Yahoo changes internals; treat as "free but fragile," not a guaranteed SLA. |
| **Alpha Vantage** | Daily/weekly/monthly OHLCV, intraday (delayed), FX, crypto, technical indicators, fundamentals, earnings calendar | **25 requests/day** on the free key (confirmed live, alphavantage.co/premium) — this is a real cut from the historical "5/min, 500/day" figure many articles/tutorials still quote; free daily-series calls also return only "compact" (last 100 points), full history needs a paid plan | Free API key via signup | Paid tiers: $49.99–$249.99/mo for 75–1200 req/min. **Free tier is now too thin to be a primary OHLCV feed** — useful only as a fundamentals/earnings-calendar supplement given the 25/day cap. |
| **Finnhub** | Real-time US stock quotes, candles, company fundamentals, earnings calendar, some alternative data | Free tier commonly cited as **60 calls/min**, but several premium-only endpoints (ownership, insider transactions, unusual options-type alternative data) — **could not re-verify the exact figure live** in this session (docs pages are JS-rendered SPAs that returned no body to the fetch tool); treat the 60/min figure as unverified-but-likely-still-current and confirm from your own API key before relying on it | Free API key required | Site (finnhub.io) still markets itself as free-tier-friendly for real-time US/forex/crypto as of Aug 2026. |
| **Polygon.io → "Massive"** | Stocks, options, indices, FX, futures reference + aggregate data, flat files, WebSockets | Free "Stocks Basic" tier (confirmed live): **5 API calls/minute, 2 years historical, end-of-day only (no real-time)**, US stocks only. Options/real-time require the $199/mo "Advanced" tier | Free API key | **Important 2026 change**: `polygon.io` now 301-redirects (root domain and `/docs/...` paths) to `massive.com`, which markets the same stocks/options/indices/FX/futures product line under a "Massive" brand. This appears to be a rebrand rather than shutdown, but it's a very recent-looking change — verify current terms directly at signup since free-tier terms may keep shifting during the transition. |
| **Twelve Data** | Real-time-ish US equities/ETFs, FX, crypto, 100+ technical indicators, reference data | Free "Basic" plan (confirmed live): **8 API calls/minute, 800 calls/day**, plus 8 trial WebSocket credits; fundamentals/bonds are paid-only | Free API key | Reasonable secondary/backup OHLCV source; batch requests supported which helps stretch the daily cap. |
| **Tiingo** | End-of-day composite US equity prices (30+ years history), 49k+ tickers | Free "Starter" plan (confirmed live): **50 req/hour, 1,000 req/day, 500 unique symbols/month, 1GB bandwidth/month**; fundamentals and news are paid add-ons ($30/mo Power plan) | Free API key | Good, generous EOD backup/cross-check source; no free fundamentals or news. |
| **IEX Cloud** | — | — | — | **Confirmed retired/shut down in August 2024** (per Wikipedia's IEX Group entry, citing its own retirement notice). Do not build against it; there is no single direct "successor" — former IEX Cloud users have scattered to Polygon/Massive, Finnhub, Twelve Data, Tiingo, or Alpaca's free market-data API. |

**Practical read:** No single free source is both generous and real-time. A realistic local pipeline is **yfinance as the primary bulk OHLCV puller** (unlimited-ish but fragile) with **Twelve Data and/or Tiingo as a cross-check/backup** when yfinance breaks, and **Alpha Vantage reserved for fundamentals/earnings calendar** rather than price bars given its 25/day cap.

---

## 2. Fundamentals Data

- **Alpha Vantage** free key: `OVERVIEW`, `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`, `EARNINGS` endpoints are documented as accessible on a free key (confirmed live at alphavantage.co/documentation), but every call counts against the same **25/day** budget — so fundamentals pulls must be batched/cached aggressively (e.g., refresh quarterly per ticker, not daily).
- **Financial Modeling Prep (FMP)**: widely used for free-tier fundamentals historically (income/balance/cash-flow statements, ratios, earnings calendar), but I could **not verify current 2026 terms live** — their pricing/docs pages returned 403 to automated fetches in this session. FMP has a documented history of shrinking its free tier over 2023–2025 (fewer years of history, fewer endpoints, added a daily call cap around 250/day on newer plans). **Verify current FMP free-tier scope directly with a fresh signup before depending on it** — do not trust older blog posts describing "250 calls/day, full statements," as that has reportedly narrowed.
- **yfinance**: pulls Yahoo Finance's summary financial statements (`Ticker.balance_sheet`, `.financials`, `.cashflow`) for free but with the same fragility caveat as above, and coverage/depth (a few years of annual/quarterly data) is thinner than a dedicated fundamentals vendor.
- **SEC EDGAR XBRL "company facts" / "frames" APIs** (see §6) are the most durable free fundamentals source since they come straight from filers' XBRL tags rather than a third-party's derived dataset — best used as the authoritative fallback/cross-check for balance sheet and income statement line items.

---

## 3. Short Interest Data

- **FINRA Equity Short Interest** (confirmed live at finra.org/finra-data): free, covers all exchange-listed and OTC equities, published **twice monthly** (settlement dates the 15th and last business day of each month), released on the 7th business day after settlement — so it is **structurally delayed by design**, not a data-access limitation. Access via: (1) an interactive web grid with 5 years rolling history, (2) downloadable historical files, (3) a documented **FINRA Query/Equity API** (developer.finra.org) for programmatic pulls of the same 5-year window.
- There is **no free real-time or near-real-time short-interest analog** to paid short-borrow-fee/utilization feeds like Ortex or S3 Partners — those require paid subscriptions. The realistic free option is FINRA's biweekly official reports, optionally supplemented by NYSE/Nasdaq's own short-interest pages (same FINRA-sourced data, same cadence) and, if useful as a rough proxy, free short-volume (not short-interest) daily files that some exchanges publish (Reg SHO daily short volume files via each exchange's FTP, e.g., Nasdaq Trader / NYSE — these are daily and free but measure *short volume*, a different and much noisier signal than short *interest*).

---

## 4. Options Data / Unusual Options Activity

This is the weakest area for a zero-budget pipeline:

- **yfinance** (`Ticker.options`, `Ticker.option_chain(date)`) is the only fully free, no-registration source for actual options chains (strikes, bid/ask, open interest, implied volatility) — delayed and unofficial, subject to the same Yahoo-scraping fragility noted above, but genuinely usable for building your own "unusual activity" logic (e.g., flag volume >> open interest, or volume spikes vs. 20-day average) rather than paying for a pre-built unusual-activity feed.
- **CBOE** publishes free delayed quotes (VIX and index/options delayed-quote dashboards) but this is a **web-viewing product, not a bulk/programmatic free API** (confirmed live — the free delayed-quotes pages exist, but CBOE's real market-data products, including the "Cboe One Options Feed," are commercial).
- **Barchart's Unusual Options Activity page** (confirmed live) is free to *view* today's data with no login, but downloads are capped at 1/day for non-members, historical filtering/screener access requires a paid "Premier" membership, and there is no free programmatic API — only commercial "OnDemand"/"Market Data" APIs.
- **Unusual Whales** and **Market Chameleon**: could not verify current free-tier scope live in this session (fetch timeouts/blocked). From general knowledge, both are primarily paid products with limited free teaser views on their websites — treat any "free" access as a marketing sample, not a stable data source, and re-verify before relying on either.
- **Practical recommendation**: build your own "unusual options" signal on top of free yfinance option-chain pulls (volume/OI ratios, IV rank vs. own historical IV) rather than looking for a free pre-packaged unusual-activity feed — none of the free sources checked offer that as an actual API product.

---

## 5. Earnings Calendars

- **Alpha Vantage** `EARNINGS_CALENDAR` endpoint is free-key accessible (confirmed live in docs) but shares the 25-calls/day budget.
- **yfinance** `Ticker.calendar` / `Ticker.get_earnings_dates()` gives free per-ticker earnings dates/estimates (confirmed live in current docs) — good for a per-symbol watchlist approach.
- **Finnhub** has historically offered a free earnings-calendar endpoint (`/calendar/earnings`) bundled at low or no cost; I could not re-confirm the exact current free-tier scope live in this session due to JS-rendered docs, so verify with your own key before depending on it.
- **Nasdaq.com's public earnings-calendar page** exists as a free web page but is not a documented public API — scraping it is possible but fragile and likely against ToS; not recommended as a primary pipeline component.
- **Practical recommendation**: use yfinance per-ticker earnings dates as the primary free source (zero API budget consumed elsewhere) and cross-check upcoming-week names against Alpha Vantage's `EARNINGS_CALENDAR` sparingly (it's a bulk CSV-style pull, so one call can cover a wide date range, easing the 25/day constraint).

---

## 6. SEC EDGAR (Filings, XBRL Fundamentals)

- SEC's own docs pages returned 403 to the automated fetch tool in this session (likely bot-blocking on sec.gov, not a policy change), so I'm relying on long-standing, well-documented SEC policy here rather than a fresh live citation — this is a very stable, multi-year-old policy and unlikely to have changed, but worth a manual browser check if precision matters:
  - **No API key required.** SEC requires a descriptive `User-Agent` HTTP header identifying your organization/app and a contact email on every request (e.g., `User-Agent: YourApp/1.0 (contact@example.com)`); requests without one get blocked.
  - **Rate limit**: SEC's stated fair-access policy is **max ~10 requests/second** to sec.gov/data.sec.gov; sustained higher rates get temporarily IP-blocked.
  - **What's available for free**: full-text search API, `data.sec.gov/submissions/CIK##########.json` (filing history per company), `data.sec.gov/api/xbrl/companyfacts/` and `companyconcept/` (structured XBRL financial statement data), and `frames/` (cross-company XBRL data for a given concept/period) — this is the most authoritative and durable free fundamentals/filings source in the whole stack, since it's the primary-source data other vendors resell.
  - Reference URL to verify directly in a browser: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces` (blocked bot fetch in this session, HTTP 403, but is the correct/current canonical documentation page).

---

## Recommended combined free pipeline

1. **Bulk OHLCV**: yfinance as primary puller (accept the "unofficial/fragile" risk; cache aggressively locally so a temporary Yahoo outage doesn't stall the whole system); Twelve Data (800 calls/day) and/or Tiingo (1,000 calls/day EOD) as an automated cross-check/fallback if yfinance's response looks anomalous or throws errors.
2. **Fundamentals**: SEC EDGAR XBRL company-facts API as the ground-truth source (free, durable, no key, just respect the 10 req/sec + User-Agent rules); Alpha Vantage `OVERVIEW`/statements sparingly (25/day budget) for quick-look ratios where XBRL parsing is overkill.
3. **Earnings calendar**: yfinance per-watchlist-ticker earnings dates as the daily driver; Alpha Vantage `EARNINGS_CALENDAR` for a periodic broad sweep.
4. **Short interest**: FINRA's official biweekly short-interest files/API (free, structurally delayed) — set expectations that this is a lagging, twice-monthly signal, not a day-trading input.
5. **Options / unusual activity**: yfinance option-chain pulls + your own volume/OI/IV-rank heuristics; treat CBOE's delayed-quote pages and Barchart's free unusual-activity view as manual/spot-check supplements only, not pipeline inputs, since neither exposes a free bulk API.
6. **Filings/news triggers**: SEC EDGAR full-text search + submissions API for 8-K/10-Q/10-K/Form 4 alerts — free, first-party, and the most reliable "something happened" trigger available without a paid news API.

**Gaps to flag to the project owner**: (a) there is no free, low-latency short-interest or unusual-options-activity data comparable to paid Ortex/Unusual-Whales-tier products — any signal built here will be a same-day-or-lagged proxy at best; (b) the two most-used free OHLCV workhorses (yfinance, and now Massive/ex-Polygon's throttled free tier) both carry real continuity risk — yfinance because it depends on an unofficial/unsupported Yahoo endpoint, and Massive because its free tier is thin (5 calls/min, EOD only) and the site itself is mid-rebrand as of this check; build in a secondary-source fallback and monitor for further vendor changes rather than assuming today's free-tier terms hold for the life of the project.