#!/usr/bin/env bash
set -euo pipefail
unset SOURCE_TOKEN GITEA_TOKEN GITHUB_TOKEN
test "$(python -c 'import sys;print(".".join(map(str,sys.version_info[:2])))')" = 3.12
python -m pip install --disable-pip-version-check \
  pytest==9.1.1 pytest-asyncio==1.4.0 pytest-cov==7.1.0 \
  pytest-socket==0.8.1 aiohttp==3.14.5 voluptuous==0.16.0
python -m pytest tests -q --disable-socket --allow-unix-socket \
  --cov=lth_pkg.auto_review --cov=lth_pkg.customer_history \
  --cov=lth_pkg.message_archive --cov=lth_pkg.services \
  --cov-report=term-missing --cov-fail-under=80
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
git diff --exit-code --
