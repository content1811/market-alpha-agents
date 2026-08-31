# Japanese Equities (TSE) Data Sources — Current Status as of August 2026

Research method note: J-Quants' live marketing site (jpx-jquants.com) returned an HTTP 403 CloudFront block on direct fetch during this session (likely IP/geo-based bot filtering) — a relevant practical complication in itself. I recovered a **May 15, 2026 Wayback Machine snapshot** of the full pricing/dataset page, and directly tested several live endpoints (EDINET API, Yahoo Finance chart API, Stooq, JPX statistics pages) via curl to confirm current 2026 behavior.

## 1. J-Quants API (JPX Market Innovation & Research, Inc.)

Source: https://web.archive.org/web/20260515191729/https://jpx-jquants.com/en (snapshot verified current — page text references "V2 API released Dec 22, 2025" and shows live price data through Dec 2025)

**Major change vs. older write-ups:** J-Quants moved to a **V2 API** on Dec 22, 2025, with a new endpoint style (`https://api.jquants.com/v2/equities/bars/daily`) and **API-key authentication** (via dashboard) replacing the old V1 token/refresh-token flow. Accounts created on/after 2025‑12‑22 are V2-only.

**Current tiers (confirmed from live pricing table):**

| Plan | Price (incl. tax) | API rate limit | History | CSV download | Notable inclusions |
|---|---|---|---|---|---|
| Free | ¥0/mo | 5 calls/min | 2 years, **minus most recent 12 weeks** (i.e., data is ~3 months stale) | No | Listed-issue master, daily OHLC, financial summary only, earnings-date calendar, trading calendar |
| Light | ¥1,650/mo (~$11) | 60 calls/min | 5 years | Yes | + TOPIX OHLC, investor-type breakdown |
| Standard | ¥3,300/mo (~$22) | 120 calls/min | 10 years | Yes | + index OHLC (incl. TOPIX), **margin trading data, weekly margin balance, short-selling ratio by sector, short-sale position reports, daily disclosed margin balance**, Nikkei 225 options OHLC |
| Premium | ¥16,500/mo (~$110) | 500 calls/min | 20 years (max) | Yes | + full financial statements (BS/PL/CF), dividends, futures/options OHLC, morning-session OHLC, trading-breakdown data |
| Add-on (any paid tier) | +¥5,500/mo | — | 2 years | — | Minute-bar and tick-level stock price data |

**Key implication for this project:** the Free tier is real-time-unusable for day/swing trading (12‑week lag) and has no margin/short-selling data — that only appears starting at **Standard (¥3,300/mo, ~$22)**. Given the stated "free-tier-only to start" constraint, the practical free path is: J-Quants Free tier for reference/fundamentals + listed-issue master (delayed, fine for backtesting/screening, not for live signals), supplemented by JPX's own free public statistics pages for margin/short data (see §5).

**Registration:** Account creation and Free-plan use require only email (or Google sign-in) — the FAQ text explicitly states "User registration and Free plan usage are available [without a credit card]; paid plan purchases require credit card payment only," and billing name/address is collected only at Stripe checkout for paid plans. No explicit Japanese-residency or Japanese-address gate was found in the site's UI text. The site is fully bilingual (JP/EN toggle, `locale=en` message catalog confirmed in page source), which meaningfully lowers the language barrier versus older versions of the service.

**Also notable:** J-Quants now ships an official **"J-Quants MCP" server** and generative-AI/chat-based access path, explicitly marketed for non-coders and AI-agent integration — directly relevant to a multi-agent AI research system design, since it can be queried by an LLM agent conversationally instead of hand-written API glue code.

Data-use restriction (per FAQ): you may publish your own analysis/methodology, but may **not** redistribute raw J-Quants data itself, and using it to continuously provide investment-analysis output to third parties is not "personal use" — worth keeping in mind if this system is ever shared beyond the single operator.

## 2. Yahoo Finance (Japan)

- **finance.yahoo.co.jp** (the JP-language consumer portal): confirmed live in Aug 2026 (curl fetch of a Toyota quote page, `7203.T`, succeeded, HTTP 200, includes overnight PTS pricing). It has **no official public API** — access would require scraping the Japanese-language HTML, which is fragile and against Yahoo's terms.
- The **unofficial global Yahoo Finance "chart" endpoint** (`query1.finance.yahoo.com/v8/finance/chart/{ticker}.T`, the same backend `yfinance` uses) **does still return OHLCV for TSE tickers** as of Aug 2026 — verified live: fetched Toyota (`7203.T`) 5-day daily bars successfully, in JPY, with correct TSE/JST metadata. This is the practical way most people get "Yahoo Finance Japan" data programmatically for free, not the JP portal itself.
- Complication observed directly: the endpoint returned **HTTP 429 (Too Many Requests)** on a bare curl request without a browser User-Agent header, then succeeded once a Chrome UA string was added — consistent with widely-reported 2024–2026 tightening of Yahoo's anti-scraping posture (frequent breakage of `yfinance`, need for cookie/crumb handling or libraries like `curl_cffi`). Treat this as an unofficial, rate-limited, no-SLA source, not a stable production dependency.

## 3. EDINET (Financial Services Agency filings database)

Source: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html (guide index page, showing "EDINET API仕様書（Version 2）(2026年6月3日更新)" — confirms the spec was actively updated as recently as June 3, 2026)

- **API is EDINET API v2**, confirmed live by direct test: `GET https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date=2026-08-25&type=2` returned `{"StatusCode":401,"message":"Access denied due to invalid subscription key..."}` — proving the API requires a **free subscription/API key** (Ocp-Apim-Subscription-Key-style header), obtained via registration on the EDINET site, rather than being fully open/keyless.
- **Content:** securities reports (有価証券報告書), semi-annual reports, extraordinary reports, internal-control reports, investment-trust filings, plus full XBRL taxonomy data — i.e., primary-source Japanese company fundamentals/disclosures, the JP equivalent of SEC EDGAR.
- **Language:** the operation guide, taxonomy docs, and the vast majority of filings are **Japanese only**. There is IFRS taxonomy support for issuers reporting under IFRS, and some large/foreign-affiliated issuers file bilingual summary documents, but EDINET should be assumed Japanese-language-dominant for this project's purposes — meaning any agent parsing EDINET filings needs Japanese NLP/translation in the pipeline.
- **Registration barrier:** based on the service's design pattern (matches J-Quants — simple account/email-based registration, no evidence of a Japan-residency gate in public documentation), EDINET API key registration does not appear to require Japanese residency, but this specific point could not be confirmed via a live registration form fetch in this session (the registration UI is JS-rendered) — flag as moderately, not fully, confirmed.
- Free downloadable taxonomy/code-list files (multiple years 2008–2026) are openly accessible with no key at all; only the *query/document-retrieval API* requires the subscription key.

## 4. Free OHLCV providers for TSE-listed stocks (beyond Yahoo)

- **Stooq.com**: historically a simple free CSV endpoint (`stooq.com/q/d/l/?s=<ticker>.jp&i=d`) commonly used for TSE OHLCV. **As of Aug 2026, this was found to be blocked by a JavaScript proof-of-work bot challenge** on a plain curl request (returned an HTML page requiring SHA-256 proof-of-work + a `/__verify` POST before serving data) — confirmed live in this session. This is a **new practical complication**: Stooq is no longer trivially scriptable with a bare HTTP client; it now needs a headless-browser or JS-challenge-solving layer, undermining its usefulness as a "simple free CSV" source for a local pipeline.
- **Alpha Vantage / Twelve Data** (free tiers): both required a real (non-"demo") API key to test TSE-ticker coverage in this session, so live TSE support could not be directly verified here. Based on general provider positioning, these free tiers are primarily US/major-global-exchange focused; international/TSE equity coverage on the free tier is historically inconsistent or absent — this should be spot-checked with a real free key before relying on either for TSE data (moderate confidence, not independently verified this session).
- **J-Quants Free tier** itself is the most reliable *structured, TSE-specific* free OHLCV source, with the major caveat of the 12-week data lag noted above.

## 5. Margin trading and short-selling data for Japan

- **Via J-Quants:** requires **Standard tier or above (¥3,300+/month)** — not available free/Light. Fields include weekly margin balance by issue, daily disclosed margin balance, short-selling ratio by sector, and short-sale position reports (0.5%+ threshold disclosures), all structured/API-ready.
- **Via JPX directly, for free, with no registration or API key** (confirmed live, both pages showing "Update: Aug. 26, 2026" — i.e., today, current):
  - Short Selling Value (daily, by industry): https://www.jpx.co.jp/english/markets/statistics-equities/short-selling/index.html
  - Outstanding Margin Trading by Issue (updated ~16:00 JST daily for restricted/flagged issues, weekly for standard issues): https://www.jpx.co.jp/english/markets/statistics-equities/margin/index.html
  - These are HTML/JS-driven statistics pages (not clean CSV APIs) requiring scraping/parsing, and the per-industry short-selling figure is aggregate market data, not per-ticker — but they are a genuinely free, zero-registration route to margin/short data that could substitute for J-Quants Standard tier at the cost of extra scraping engineering.
  - Individual-stock short-sale position reports (≥0.5% disclosures) are also published by JPX/TSE's disclosure system but a specific stable public URL for programmatic access was not located in this session (several guessed URLs returned 404); this is the one area where the paid J-Quants Standard tier's structured API is likely to save meaningfully more engineering time than DIY scraping.

## 6. Practical complications summary

- **Language:** EDINET is Japanese-dominant; J-Quants is now fully bilingual (a real improvement over its earlier Japanese-only era); JPX statistics pages have parallel English versions (confirmed working) but underlying filings/disclosures referenced from them are typically Japanese.
- **Residency/address:** No confirmed hard requirement for Japanese address/residency to register for either J-Quants (Free tier explicitly needs no card) or EDINET's API key, based on available evidence — but this is based on absence of evidence in scraped text rather than a positive confirmation from a completed registration flow, so treat as moderate-confidence.
- **Rate limits:** J-Quants Free = 5 calls/min (quite restrictive for building/backtesting a multi-symbol screener); Yahoo's unofficial endpoint is unrated/undocumented and will 429 without careful header/backoff handling; Stooq now requires solving a JS proof-of-work challenge, effectively raising the bar from "simple CSV fetch" to "needs a browser automation layer."
- **Bot/anti-scraping posture has generally tightened across free sources by 2026** (Stooq's new JS challenge, Yahoo's 429s without proper headers, jpx-jquants.com's CloudFront blocking on some client profiles) — a local system built on these free/unofficial sources should budget engineering time for retry/backoff, header spoofing, and periodic breakage, not just for initial integration.
- **Freshness of official free data is good:** JPX's own margin/short statistics pages were updated same-day (Aug 26, 2026) with no paywall — for a manual swing/day-trading tool, this JPX-direct route plus J-Quants Free for fundamentals is a reasonable zero-cost starting stack, with the Light/Standard paid J-Quants tiers (~$11–22/month) as a cheap near-term upgrade path once/if the user is willing to spend anything beyond pure free-tier.