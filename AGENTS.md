# Personal Local Trailer Hire integration

- Private VM300 `hallyaus/localtrailerhire`, Git SSH2222, is primary. Preserve
  main, tags and local work. Push completed validated source there first, then
  identical existing public GitHub recovery with Actions disabled. Keep HACS
  public compatibility URLs until a verified replacement exists.
- Only personal-ubuntu validates this source. Preserve the original Python3.12
  complete unit suite, four-module coverage and80% threshold, plus official
  hassfest. Block external test sockets and use existing scripted fake clients.
- Never log in to Sharetribe/LocalTrailerHire, send messages/reviews, accept or
  cancel bookings, change listings, copy customer archives, operate HA or use
  actual tokens as a CI/migration test. Existing auto-review and booking/service
  behavior must remain unchanged; CI is not permission to enable those actions.
- Retain a private exact-source candidate only after unit and metadata checks.
  HACS validation is separately manual and requires the approved repository-only
  HACS_PUBLIC_READ_TOKEN and identical public source. Never send a Gitea token
  to GitHub or ignore original release checks. Do not create tags/releases,
  publish, install/reload the integration or restart HA by default.
- Use existing plans and allowances; leave M4T, Proxmox.99 and Kidde alone.

Current evidence and schedule/distribution holds are in docs/GITEA-CUTOVER.md.
