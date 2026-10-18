# Personal source validation route

The original GitHub source at88f44140de8727b77d1b690e83f2871178b88d45 has a
Python3.12 unit job with80% coverage across auto_review, customer_history,
message_archive and services. All original tests and that coverage threshold
are retained on the separate personal Gitea runner. Fake session/provider
tests remain offline; external sockets are additionally blocked.

The dependent official pinned hassfest image validates exact private source.
A final job packages tracked integration files, HACS metadata, README, license
and changelog, with source/tree/SHA256 provenance in a private three-day
artifact. It never publishes or installs the candidate. No application source,
integration version, booking/review/message behavior or release tag changed.

The existing public GitHub recovery/HACS URLs stay intact. A manual pinned
official HACS gate is prepared for the identical public recovery SHA, using
only the repository-level HACS_PUBLIC_READ_TOKEN after the approved user
credential handoff. It has not run. Full source CI does not establish HACS
distribution, a published release or an installed production integration.
The historical manual release requires pytest, hassfest and HACS checks; those
requirements are not replaced by package generation alone.

The original daily06:00UTC validation cadence remains deferred until complete
initial Gitea validation and artifact proof pass. No cron is activated by this
initial enrollment. No actual marketplace/customer/HA request is performed.

Initial498 now passed all original unit/coverage gates (88.28% against the80%
threshold), official hassfest and private packaging. Independent stored-artifact
verification matched all25ZIP files to exact VM300 source, and identical public
recovery was inert. The original daily06:00UTC cadence is now enrolled for these
same unchanged private CI jobs. Registration and a real scheduled firing remain
separate evidence; no public HACS, release, installed integration or live
marketplace behavior is certified by this source route.

Pinned test-tool versions were checked against primary PyPI release metadata:
https://pypi.org/project/pytest/9.1.1/
https://pypi.org/project/pytest-asyncio/1.4.0/
https://pypi.org/project/pytest-cov/7.1.0/
https://pypi.org/project/pytest-socket/0.8.1/
