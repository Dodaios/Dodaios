# Public plugin marks

Files here are served verbatim at `/plugin-assets/…` so a plugin manifest's
`logo_url` can point at them. The Plugins and Marketplace views prefer the
ledgered mark in `src/assets/brands/` whenever one exists; a file here is only
the manifest's own reference. Every logo file needs a row below, and
`scripts/ci/check_brand_logos.py` fails on one without it.

Every mark belongs to its owner and is used solely to identify the service a
plugin connects to (nominative use). It does not imply endorsement.

| Asset | Source | Legal basis | Added |
| --- | --- | --- | --- |
| `agentmail.ico` | AgentMail's own favicon, `https://www.agentmail.to/favicon.ico`, byte-for-byte (same source as `src/assets/brands/agentmail.png`) | vendor asset | 2026-09-10 |
