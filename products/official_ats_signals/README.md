# AION Official ATS Hiring Signals — a market-validation candidate

**Status: source code only. NOT published or earning. Not wired into the live Temple.**

## Product and demand evidence

Automated clients and human developers can supply 1–5 employer job board
identifiers and receive up to 100 filtered, normalized job records with original
source URLs, title, location and only explicitly published details. Sources are
the public, employer-facing Greenhouse, Lever and Ashby APIs. The product
adds source verification and consistent format. It does not promise interviews,
vacancy validity in the future, guaranteed client demand, or valid emails.

Apify's public Store API in October 2026 showed existing demand for automated
job collection: curious_coder/linkedin-jobs-scraper had approximately 17,700
distinct users and 490k runs in 30 days. This is usage evidence, NOT proof that
this new specialized variant will sell or that every competitor run was paid.
The competitor's published event price was approximately $0.002/job. Do not
misrepresent a raw listing as a high-value $2 insight.

The product is original code using the Apache-2.0 licensed Apify Python SDK
and public vendor APIs; it does not copy any proprietary competitor.

## Local use

Collector needs only Python stdlib; tests use pytest.

    python -m pytest tests/test_official_ats_signals_actor.py

Source-only example from repo root:

    python -c 'from products.official_ats_signals.collector import collect; print(collect([{"provider":"ashby","slug":"Ashby"}], title_keywords=["engineer"],max_results=5))'

Apify actor folder is products/official_ats_signals/ with .actor/ and Dockerfile.

## Charging — NOT ENABLED

Working price hypothesis: $2 per successful bounded batch of matching, official
source records (up to 50 by default), not $2 per individual raw posting.
This price is unvalidated. Apify PPE needs a one-time event called
"verified-batch", configured in Apify Console, with no additional nonzero
dataset-item charge. Seller must complete KYC, payout setup and cost checks.
Only then set environment AION_HIRING_PPE_ENABLED=1.

With charging disabled, the product returns a **maximum of 2 preview rows**.
A failed/empty lookup is never billed. In paid mode the code charges once only
after finding a nonempty result, respects the caller's max charge, and emits
the full result after the charge succeeds.

Illustrative unit economics, NOT a forecast: with a $2 paid batch, Apify's
20% platform revenue share leaves $1.60 BEFORE compute/platform run costs.
63 paid batches/day = $126 gross/day and $100.80 before compute costs. Volume,
conversion, marginal costs and realized merchant proceeds remain UNKNOWN.

No source data is sent to a paid third-party API beyond the official job
board GET request. Maximum 5 boards, one GET per board, 2MB response cap,
10 seconds per request, no redirects or arbitrary hosts. No identity/session
claims, unsolicited messaging, applicant info, job application submissions,
credential collection, proxy evasion or scraping behind logins.

## Commercial gates

1. Offline regression tests and live official source validation pass.
2. Seller's account/KYC/payout verified, official Actor published in preview.
3. Bounded platform cost observed, price/event configured by seller.
4. First independent, non-self-paid charged Actor run documented.
5. Repeat paid users and positive unit margin before adding more products.

The existing AION Base USDC product price and production configuration remain
unchanged. Do not claim this product has earned revenue before a platform
payment record confirms it.

Official APIs:
- https://docs.greenhouse.io/job-board.html
- https://github.com/lever/postings-api
- https://developers.ashbyhq.com/docs/public-job-posting-api
- https://docs.apify.com/actors/publishing/monetize
