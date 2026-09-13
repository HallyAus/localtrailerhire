# Changelog

## 1.6.1

- Verify Sharetribe's currently offered process transitions before posting an
  automatic or manual provider review; cancelled and terminal transactions now
  fail closed without a review POST.
- Add the opt-in auto-review controls to initial setup, improve sanitized retry
  diagnostics, and require an explicit transaction ID for manual retries.
- Register Home Assistant actions during integration setup and keep them
  available for automation validation even when a config entry cannot load.
- Make config-entry startup transactional while preserving integration-wide
  actions and unwinding partially loaded platforms safely.
- Stop retaining account passwords after Sharetribe issues a refresh token and
  persist every later rotating token immediately, including service-triggered
  refreshes.
- Report partial and failed message-history syncs honestly, avoid unchanged
  storage writes, resume capped historical backfills, serialize clear/sync
  mutations, avoid duplicate same-poll requests, and tolerate malformed legacy
  archive records.
- Omit residential and pickup addresses from entity attributes and archives
  unless sensitive-data collection is explicitly enabled.
- Discover new listing entities after startup without creating duplicates.
- Use the current Home Assistant OptionsFlow API and ship HACS validation with
  no ignored checks.
- Correct the release workflow to match HACS source-archive distribution and
  expand restart, troubleshooting, privacy, and HACS submission documentation.
