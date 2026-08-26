# Local Financial News Monitoring & Alerting — Free-Tier Research (verified live, 2026-08-26)

All sources below were checked live today (responses show 2026-08-26 timestamps/dates), not from stale training data. URLs cited throughout.

## 1. Free News/Filing Data Sources

**Finnhub** (https://finnhub.io/docs/api, https://finnhub.io/pricing)
- Free tier still exists; `general_news` (category-based market news) and `company_news` (ticker-scoped) endpoints confirmed structurally live (tested `/api/v1/news?category=general` and `/api/v1/company-news`, correctly rejected the invalid demo token, confirming the endpoints are active and gated by API key, not deprecated).
- Historically documented free-tier limit is 60 API calls/minute — I could not scrape the exact current limits table because Finnhub's pricing/docs pages are a JS-rendered React SPA that doesn't expose numbers to a plain HTTP fetch. **Verify the exact current cap in your own dashboard after signup** rather than trusting any cached figure, including mine.
- Sentiment-scored news and some premium news filters require a paid plan; raw headline/summary retrieval is the free-tier-viable path.

**NewsAPI.org** (https://newsapi.org/pricing) — confirmed unchanged in 2026:
- Free "Developer" tier: **100 requests/day**, **24-hour article delay**, and explicitly **"cannot be used in a staging or production environment (including internally)"** — i.e., strictly dev/test, not licensed for a live personal trading tool under their ToS as written. Treat this as a prototyping-only source, not a production feed.

**SEC EDGAR (real-time, free, no key)** — this is the strongest free source in the whole stack:
- The classic "current filings" Atom feed `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=10&output=atom` is live today and returned an 8-K filed literally hours before this research (Bath & Body Works, filed 2026-08-26 07:17 EDT) — confirmed real-time, no API key required.
- Fair Access Policy (https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data): **max 10 requests/second**, must send a descriptive `User-Agent` header (name + contact email), no botnets/automated crawling outside that policy. For a personal single-operator tool, polling every 1–5 minutes is well within bounds.
- No EDGAR full-text-search API page was fetchable directly (403 on that specific doc URL — likely a bot-blocking edge case, not a service outage), but the getcurrent/company Atom feeds and static JSON submissions endpoints are the practical, well-established path.

**Crypto RSS** — both confirmed live/valid RSS 2.0 today:
- CoinDesk: `https://www.coindesk.com/arc/outboundfeeds/rss/` — valid, hourly updates, dated 2026-08-26.
- CoinTelegraph: `https://www.cointelegraph.com/rss` — valid, hourly updates, dated 2026-08-26.

**Major outlet RSS (US)** — all returned HTTP 200 with correct `application/xml` content-type today:
- MarketWatch (Dow Jones feed): `https://feeds.content.dowjones.io/public/rss/mw_topstories`
- CNBC: `https://www.cnbc.com/id/100003114/device/rss/rss.html`
- Yahoo Finance: `https://finance.yahoo.com/news/rssindex`
- Seeking Alpha: `https://seekingalpha.com/market_currents.xml`
- Investing.com: `https://www.investing.com/rss/news.rss`
- Reuters: `reutersagency.com/feed/` still resolves (301 redirect, then 200) but this is Reuters' corporate/agency blog feed, not a general markets-news firehose — Reuters discontinued its broad public news RSS years ago; don't rely on it as a primary feed.

**Japan-market news gap (flag for the JP-equities part of scope):**
- Nikkei has **no free public RSS/API** — guessed standard RSS path returned 404; it's a paywalled site with no retail-friendly free feed.
- Working free JP sources confirmed live today: Japan Times (`https://www.japantimes.co.jp/feed/`, 200), NHK business category (`https://www3.nhk.or.jp/rss/news/cat5.xml`, 200), Yahoo Japan News business (`https://news.yahoo.co.jp/rss/topics/business.xml`, 200) — all general-interest/English-or-Japanese business news, not TSE-filing-specific.
- **TDnet** (Tokyo Stock Exchange's timely-disclosure portal, `https://www.release.tdnet.info/inbs/I_main_00.html`) — confirmed live (200) and free/keyless, and is the closest JP equivalent to EDGAR for company disclosures. However, unlike EDGAR it has **no clean Atom/RSS/JSON feed** — it's an HTML-only browse interface (`robots: noindex,nofollow`), so building a JP equivalent of your EDGAR watcher means writing an HTML scraper/poller rather than consuming a feed. This asymmetry (easy real-time EDGAR feed vs. scrape-only TDnet) is worth calling out explicitly to the project owner as added engineering cost on the JP-equities leg.

**Bonus free option worth adding — Alpha Vantage `NEWS_SENTIMENT`** (tested live with `apikey=demo` today, returned real current articles with pre-computed sentiment):
- Gives ready-made bearish/neutral/bullish + relevance scores per article, no custom LLM scoring needed.
- But free tier is only **25 requests/day** (confirmed at https://www.alphavantage.co/premium/ ) — too thin for continuous monitoring; useful only as an occasional cross-check, not the primary feed.

## 2. X/Twitter API — Major 2026 Change to Flag

Checked `https://docs.x.com/x-api/getting-started/about-x-api` and its pricing sub-page directly:
- X has moved to a **pure pay-per-usage, credit-based model with no subscription tiers and, critically, no free tier at all** for reads or most writes. Costs run ~$0.001–$0.010 per read resource and $0.015–$0.20 per write, prepaid credits required upfront, no minimum spend but a positive balance is mandatory to make any call.
- The old Free/Basic-$200/Pro-$5000 subscription structure referenced in a lot of older material is gone; even the previously-available very-limited free write-only tier is not mentioned anywhere in current docs.
- **Conclusion for this project: X/Twitter is not usable within a free-tier budget in 2026** — even light retail experimentation requires a funded credit balance. Recommend dropping X monitoring from the design entirely, or treating it as a future paid add-on, not part of the free-tier baseline.

## 3. LLM-Based Headline Sentiment Scoring — Local, Free Options

- **FinBERT** (`ProsusAI/finbert` on Hugging Face) — confirmed still heavily active in 2026 (4.9M downloads last month, 100+ derivative Spaces/fine-tunes). BERT-scale, runs comfortably on CPU, outputs positive/negative/neutral softmax probabilities per headline. This is the cheapest, fastest, most battle-tested local option for bulk headline triage.
- **Local LLM via Ollama** (`https://ollama.com/library`, checked live) — current small models suitable for a single-machine setup: Gemma 3 (270M), Qwen2.5/3.5 (0.5B–8B), Phi-4-mini (3.8B), Llama 3.2 (3B), Mistral 7B. Practical pattern: prompt the local model to return strict JSON (`{"score": -1..1, "confidence": 0..1, "rationale": "..."}`) per headline/cluster, using FinBERT as a fast first-pass filter and the local LLM for a second-pass, context-aware read on the subset of headlines that pass a relevance/magnitude threshold (keeps latency and CPU load manageable on a single machine).
- Given the realistic-skepticism framing requested: headline-only sentiment (from either FinBERT or a small local LLM) is a noisy, high-recall/low-precision signal at best — appropriate as one input feeding a composite score and human alert, not as a standalone trade trigger, especially at micro account sizes where slippage/spread easily swamps any edge from sentiment alone.

## 4. Local Alerting

- **Telegram Bot API** (`https://core.telegram.org/bots/api`, `.../bots/faq`) — confirmed free, HTTPS-only, token from BotFather, supports webhook or long-polling. Documented rate limits: ≤1 msg/sec per chat, ≤20 msgs/min in a group, ≤~30 msgs/sec broadcast cap (irrelevant at single-operator alert volumes; the 1000/sec paid-Stars tier is not relevant here). This is the simplest, most robust free channel for the design — recommend it as the primary alert channel.
- **Discord webhooks** (`https://docs.discord.com/developers/resources/webhook`, `.../topics/rate-limits`) — confirmed free, no bot/auth needed for a simple incoming webhook POST. Global bot API cap is 50 req/sec (far above personal-alert needs); repeated invalid requests (401/403/404/429) trigger a temporary IP throttle (10,000 invalid reqs/10 min), so just handle webhook-deleted errors gracefully.
- **SMTP email** — not separately re-verified today since it's a stable, decades-old mechanism (Gmail/other providers' free SMTP relay with an app password); no 2026-specific change expected or found.
- **macOS desktop notifications** — tested live on this machine (macOS 26.5.2 "Tahoe"): `osascript -e 'display notification "test" with title "Test"'` executed without error, confirming `display notification` still works locally in current macOS. Note first invocation typically requires a one-time Notification-permission grant to Terminal/the invoking process in System Settings; `terminal-notifier` remains a viable third-party alternative for more control (icons, sound, click actions).

## 5. Local Scheduling

- **APScheduler**: current stable is **3.11.3** (checked PyPI JSON metadata directly). The rewritten **4.0 line is still alpha** — last alpha (4.0.0a6) shipped April 2025, no stable 4.0 release as of August 2026. **Recommendation: build on APScheduler 3.x**, not 4.0, since the latter is still pre-release nearly a year and a half after that alpha.
- **cron / macOS `launchd`**: no material 2026-specific change found or expected; `launchd` remains Apple's recommended mechanism over legacy `cron` on modern macOS (cron still technically works but launchd is the sanctioned, better-integrated scheduler for user-level recurring jobs, plists in `~/Library/LaunchAgents`). For a single local research pipeline, either a long-running APScheduler process supervised by a `launchd` plist (auto-restart on crash/login) or a plain launchd-triggered Python script on a fixed interval are both reasonable; the APScheduler+launchd combo is more resilient if the machine sleeps/reboots.

## Key 2026-specific flags for the project owner

1. **X/Twitter is effectively free-tier-dead** in 2026 — pure pay-per-credit, no free access at all. Drop it from the free-tier design.
2. **NewsAPI.org free tier explicitly forbids production/internal use** in its ToS text — fine for prototyping, not for a "live" personal tool if read literally; Finnhub + RSS + EDGAR are the more defensible free backbone.
3. **APScheduler 4.0 is still alpha** — don't design around it; use 3.x.
4. **EDGAR gives you real-time, free, keyless filing alerts out of the box; TSE/JPX does not** — TDnet is free but HTML-scrape-only, a real added-complexity gap for the Japan-equities leg.
5. Finnhub's exact current free rate-limit number couldn't be scraped today (JS-rendered pricing page) — verify in-dashboard rather than trusting cached "60/min" folklore.