# Public arts lecturer notice feed

Hourly metadata monitor for publicly accessible Hibrain lecturer recruitment notices.
Focus: modelling, fashion, theatre and film teaching only; general notices without matching subject keywords are excluded.

The standard GitHub-hosted macOS runner checks at minute 01 every hour (scheduling may be delayed).
`feed.json` contains public titles, original links, keyword matches and collection health only.
No Telegram credentials, chat IDs, subscriber information or private repository configuration are included.
Full notice bodies and attachments are processed transiently and are not republished.
`state.json` tracks previously seen public titles. Initial existing notices are a baseline, not new events.
Historical feed events remain available so downstream consumers can deduplicate and recover after outages.

Run: `pip install -r requirements.txt && python collect.py`.
No AI API is used. Read original notices for eligibility, subjects, dates and attachments.
Image PDFs and unsupported attachments may require manual review; collection failures are reported.
GitHub may disable scheduled workflows in inactive public repositories; hourly metadata commits keep this repository active while successful.
