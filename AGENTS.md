## Canonical GitHub source and self-hosted Actions (2026-10-22)

GitHub `https://github.com/HallyAus/localtrailerhire` is authoritative for source, commits and releases. Push to the verified GitHub remote and current project branch, not any retired internal forge or recovery mirror. Preserve local work and never force push. Use the configured self-hosted GitHub Actions runner where available, checking actual job labels, runner trust and workflow configuration. Keep existing release gates, production settings, credentials boundaries, rollback, stage/promotion and live validation. Neither a push nor green CI alone proves deployment. Historical source-control instructions below are superseded.

# Personal Local Trailer Hire integration

- GitHub HallyAus/localtrailerhire is the authoritative source. Preserve main, tags, local work and public HACS compatibility URLs until a verified replacement exists.
- Only the configured personal self-hosted runner validates this source. Preserve the original Python3.12
  complete unit suite, four-module coverage and80% threshold, plus official
  hassfest. Block external test sockets and use existing scripted fake clients.
- Never log in to Sharetribe/LocalTrailerHire, send messages/reviews, accept or
  cancel bookings, change listings, copy customer archives, operate HA or use
  actual tokens as a CI/migration test. Existing auto-review and booking/service
  behavior must remain unchanged; CI is not permission to enable those actions.
- Retain a private exact-source candidate only after unit and metadata checks.
  HACS validation is separately manual and requires the approved repository-only
  HACS_PUBLIC_READ_TOKEN and identical public source. Never send a retired-server token
  to GitHub or ignore original release checks. Do not create tags/releases,
  publish, install/reload the integration or restart HA by default.
- Use existing plans and allowances; leave M4T, Proxmox.99 and Kidde alone.
