# Free-Tier Crypto Market-Data Sources for a Local, Zero-Budget Research System (verified August 26, 2026)

## Verification note

Findings below come from live fetches of vendor pricing/docs pages on 2026-08-26 (direct fetch, plus a read-through proxy for pages that render client-side via JS and returned empty bodies to the plain fetch). Two flags worth calling out up front because they cut against commonly-repeated older assumptions:

1. **Glassnode's free API tier appears to have been discontinued.** Its live pricing page (`studio.glassnode.com/pricing`) currently lists only two paid tiers — "Advanced" and "Professional" — with no $0 option. Do not plan the pipeline around a free Glassnode API; see §2.
2. **LunarCrush's free "Hobby" tier is market-data only** (price/volume), **not** social/sentiment data. Sentiment/social metrics require a paid plan starting at $90/mo. See §4.

Where a page blocked automated fetching (403s from CryptoPanic, Bybit, Kraken, Coinbase docs — likely bot-detection, not a policy signal) I've said so explicitly and relied on well-established, stable API behavior instead of guessing at numbers that may have changed.

---

## 1. Price / Market Data

| Source | What it provides | Free-tier limits | Key/registration | 2026 status |
|---|---|---|---|---|
| **CoinGecko API (Demo plan)** | Spot prices, market cap, volume, 50+ market-data endpoints, 2 years of historical data, REST/WebSocket/webhook support | **100 calls/min, 10,000 call credits/month** (confirmed live on the pricing page) | **Free API key now required.** A fully-anonymous keyless public endpoint is no longer the documented path — you must create an account and generate a "Demo API key" via the Developer Dashboard | Still free ($0, no credit card), but **attribution is required** (link to CoinGecko's branding guide) and paid "Analyst/Lite/Pro" tiers exist above it for higher volume |
| **CoinMarketCap API (Basic plan)** | Latest quotes, market cap/volume/rankings, metadata, categories, new listings, market pairs — 60+ endpoints | **15,000 credits/month, 50 requests/min**, 60-second data staleness, 1 currency conversion/call; historical depth capped at 1 month intraday / 1 year daily | Free key via signup, **or** the newer **"Keyless Public API"** — a curated subset of endpoints usable with **no signup/key at all** | Basic plan includes limited commercial-use rights (one product, ≤100k users); no major 2026 free-tier cuts found |
| **CCXT library** | Unified REST/WebSocket client for 100+ exchanges (Binance, Coinbase, Bybit, Kraken, OKX, KuCoin, etc.) — normalizes tickers, order books, trades, and OHLCV across venues | No CCXT-imposed limit — you inherit each exchange's own public rate limits (see §3 for Binance/Bybit specifics); CCXT includes a built-in `rateLimit`/throttler per exchange | **No key needed for public market-data calls** (ticker, order book, trades, OHLCV) on virtually every supported exchange — keys are only required for private/trading endpoints | Actively maintained: **v4.5.75** on PyPI as of this check, ~99,800 commits on GitHub, MIT-licensed, `pip install ccxt` |

Sources: coingecko.com/en/api/pricing; docs.coingecko.com/reference/authentication; docs.coingecko.com/reference/setting-up-your-api-key; coinmarketcap.com/api/pricing; github.com/ccxt/ccxt; pypi.org/project/ccxt.

**Practical read:** CCXT hitting exchange REST endpoints directly is the most generous and lowest-latency free price source (no monthly credit ceiling, near-real-time). CoinGecko's Demo plan is the best broad cross-market aggregator (market cap rankings, "coin universe" discovery) now that it requires a free key. CoinMarketCap's Keyless Public API is a nice zero-friction tertiary cross-check with no signup at all, but it's a "curated subset," so don't rely on it for anything beyond spot-checking.

---

## 2. On-Chain Data

| Source | What it provides | Free-tier limits | Key/registration | 2026 status |
|---|---|---|---|---|
| **Glassnode** | 1,700+ on-chain/market metrics across 1,500+ assets (Studio/API products) | **No free tier found.** Live pricing page shows only paid plans: "Advanced" (40+ market / 270+ on-chain metrics, 4 years history at daily resolution, "API Light" limited to 14-day history + 50 calls/day, personal-use license) and "Professional" (570+ on-chain metrics, up to 15 years / 10-min resolution, flexible credit-based API, bulk endpoints, commercial license) | Account required regardless of tier; no $0 signup path found | **Flag: appears deprecated/repriced since the "free 10-req tier" era.** Treat Glassnode as **out of budget** for a zero-cost pipeline; use it only if the project's budget assumption changes |
| **Etherscan (V2 unified API) + other free explorers** | Address/tx/token balances, contract ABI/source, gas oracle, supply data, event logs — now **60+ EVM chains under a single API key** via a `chainid` parameter (Etherscan V2 merged the formerly separate BscScan/PolygonScan/Arbiscan/etc. keys into one) | Free plan: **3 calls/sec, up to 100,000 calls/day**, PRO-only endpoints excluded (paid "Lite/Standard/Advanced/Professional/Pro Plus" tiers step up to 5–30 calls/sec and 100k–1.5M calls/day, with PRO endpoints unlocked from "Standard" up) | Free API key required (signup) | Actively developed; the V2 multichain-under-one-key change is the notable 2025–2026 upgrade. For non-EVM chains, free no-key alternatives exist: **mempool.space** (Bitcoin, generous, no key) and **Blockstream Esplora** (Bitcoin, no key); **Blockchair** offers a free tier across several chains (BTC/ETH/etc.) with modest daily limits |
| **Dune Analytics** | Custom SQL over indexed on-chain data (EVM chains, Solana, etc.), dashboards, and a query-execution API | **Free plan does include API access**: ~15 requests/min on "low-limit" (write-heavy, e.g. triggering a query execution) endpoints and ~40 requests/min on "high-limit" (read-heavy) endpoints; workspace-side the free plan is 1 seat, viewer role, 1 concurrent query, 30-min query timeout, queries expire after 3 months, internal-use-only license | Free account + free API key | Paid tiers scale credits/seats/concurrency (Analyst: 4,000 credits/mo, 3 seats; Plus: 25,000 credits/mo, 10 seats); no sign of the free plan being cut, but it is clearly positioned as a trial/hobby tier rather than a production data feed |

Sources: studio.glassnode.com/pricing; docs.glassnode.com/basic-api/* ; docs.etherscan.io; etherscan.io/apis; dune.com/pricing; docs.dune.com/api-reference.

**Practical read:** With Glassnode effectively off the table for $0, the realistic free on-chain stack is **Dune Analytics** for anything requiring custom logic/joins across on-chain events (whale flows, exchange netflows you define yourself) plus **Etherscan V2** for direct address/contract/token lookups across most EVM chains with one key, supplemented by chain-specific free explorers (mempool.space/Blockstream for Bitcoin) where Etherscan doesn't apply.

---

## 3. Derivatives Data (Funding Rates, Open Interest)

| Source | What it provides | Free-tier limits | Key/registration | 2026 status |
|---|---|---|---|---|
| **Binance Futures public REST** | Funding rate history (`/fapi/v1/fundingRate`), current mark/funding (`/fapi/v1/premiumIndex`), open interest (`/fapi/v1/openInterest`), open-interest historical stats (`/futures/data/openInterestHist`) | Public market-data endpoints are **unauthenticated** — no key needed. Rate limiting is weight-based per IP (`/fapi/v1/exchangeInfo` returns current weight limits); exceeding it returns HTTP 429, with escalating IP bans (minutes to days) for repeat abuse | No key for these endpoints (keys only needed for account/trading endpoints) | Stable, heavily used public API; check `exchangeInfo` at runtime for current weight caps rather than hardcoding, since Binance tunes these periodically |
| **Bybit V5 public market endpoints** | Funding rate history (`/v5/market/funding/history`), open interest (`/v5/market/open-interest`), tickers, klines | Public endpoints require **no API key**. Bybit's documented general IP-level cap is **600 requests per 5-second window per IP** (applies broadly; authenticated/trading endpoints have separate, tighter per-UID limits not relevant to public market data) | No key for public market data | Actively maintained V5 unified API; docs at bybit-exchange.github.io/docs/v5 |
| **Other exchanges via CCXT** | OKX, Kraken Futures/Derivatives, Deribit, Bitget, etc. all expose free public funding-rate/open-interest REST endpoints, reachable either raw or through CCXT's unified `fetchFundingRateHistory`/`fetchOpenInterest` methods where implemented per-exchange | Varies by venue; generally IP-based, no key, low-to-moderate limits (hundreds of requests/minute range) | No key for public data | CCXT's per-exchange method-support matrix should be checked, since not every exchange implements every unified method identically |

Sources: developers.binance.com/docs/derivatives/usds-margined-futures; bybit-exchange.github.io/docs/v5/rate-limit; github.com/ccxt/ccxt (method/exchange capability tables).

**Practical read:** Derivatives data is the cheapest category here — every major venue publishes funding rate and open interest as free, keyless, public REST data, rate-limited only by IP. Pulling directly from Binance and Bybit (either raw REST or via CCXT for a unified schema) covers the bulk of retail-visible perp/futures positioning data at zero cost.

---

## 4. News / Sentiment

| Source | What it provides | Free-tier limits | Key/registration | 2026 status |
|---|---|---|---|---|
| **CryptoPanic** | Aggregated crypto news feed with community "bullish/bearish" votes (a crude but usable sentiment signal), currency filtering, portfolio-linked feeds on higher tiers | Documented plan structure is **Developer / Growth / Enterprise**, gated by feature (portfolio access, `size`/pagination, `last_pull`/`panic_period`/search reserved for Growth+/Enterprise) and by rate: examples in the docs show **~2 requests/sec with a ~1,000 calls/month ceiling** at the low end, scaling to ~10 req/sec / ~300,000 calls/month at the high end. **Could not confirm exact dollar pricing live** — the API docs page doesn't publish $ amounts (403'd on some fetch attempts, likely bot-blocking); verify current Developer-tier price (historically free/very low-cost) at signup | **Registration + `auth_token` required for every request** — there is no keyless public mode | Actively running; confirm current Developer-tier pricing/limits directly at signup since figures weren't published on the fetched page |
| **LunarCrush** | Social/creator/AI-driven sentiment and engagement metrics across crypto, stocks, and 50+ topic categories — **on paid tiers**. The free tier is narrower | Free **"Hobby"** plan: **market data endpoints only, 4 requests/min, 100 requests/day** — no social/sentiment/creator/AI data included. Paid: Individual $90/mo (10 req/min, 2,000/day) → Builder $300/mo → Scale $900/mo → Enterprise (custom), which is where social/sentiment access actually unlocks | Free signup for Hobby tier | **Flag: the free tier does not deliver the sentiment data LunarCrush is known for.** For actual social/sentiment metrics, budget is required — this source does not fit a strict $0 constraint beyond basic market data (which is redundant with §1 sources) |

Sources: cryptopanic.com/developers/api; lunarcrush.com/pricing; lunarcrush.com/developers/api.

**Supplementary free, no-key sentiment signal (not verified live this session, but a long-standing stable public endpoint):** the **Crypto Fear & Greed Index** at `api.alternative.me/fng/` has for years been a free, keyless JSON endpoint aggregating volatility/momentum/social/dominance/survey inputs into a single 0–100 sentiment score. Worth including as a cheap supplementary signal precisely because LunarCrush's free tier doesn't cover sentiment — but re-verify it's still live before depending on it, since it wasn't checked in this session.

**Practical read:** News/sentiment is the weakest free category. CryptoPanic's Developer tier is the realistic base for headline aggregation + crude crowd-sentiment votes, provided its low monthly cap (~1,000 calls) is respected via caching/batching. LunarCrush should be treated as a market-data-only free source, not a sentiment source, unless the budget later stretches to its $90/mo Individual plan.

---

## Recommended combination for a robust free pipeline

For a $0, local retail research system: use **CCXT against exchange REST endpoints (Binance, Bybit, Kraken, Coinbase)** as the backbone for spot/futures OHLCV, order-book snapshots, funding rates, and open interest — it's keyless for all of this, has the highest effective rate ceilings, and gives the freshest data. Layer **CoinGecko's Demo API** (free key, 100 calls/min, 10k/month) on top for broad market-cap rankings, coin discovery/metadata, and cross-venue price sanity-checks, with **CoinMarketCap's Keyless Public API** as a zero-signup tertiary cross-check. For on-chain analytics, skip Glassnode (its free tier is gone) and instead combine **Dune Analytics' free API** (custom SQL, ~15–40 req/min) for whale-flow/exchange-netflow-style derived metrics with **Etherscan's V2 unified key** (60+ EVM chains, 3 req/sec / 100k calls/day free) for direct address/contract/token lookups, adding chain-specific free explorers (mempool.space, Blockstream) where needed for non-EVM chains like Bitcoin. Round out sentiment with **CryptoPanic's Developer tier** for news + crowd votes (cache aggressively against its ~1,000 calls/month cap) plus the free, keyless **Fear & Greed Index** as a lightweight numeric sentiment gauge — treating LunarCrush as a market-data-only free source rather than a sentiment feed unless the budget expands.
