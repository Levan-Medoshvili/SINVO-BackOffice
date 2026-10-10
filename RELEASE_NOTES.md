# SINVO BackOffice — Staging release notes

## New features
- No newly documented end-user features in this release.

## Improvements
- Added a Staging pipeline that packages BackOffice and publishes it to SINVO Update Server for manual approval.
- Added artifact-size reporting and authenticated SHA-256-verified publication.

## Bug fixes
- Resolved the publisher credential setup problem; authenticated release publishing now succeeds.

## Technical changes
- Builds are registered as inactive releases; the Staging pipeline does not install them on the BackOffice server.

Update this file when user-facing functionality changes. Remove items that are not part of the next release.

## Installation enrollment
- New BackOffice instances can create a durable unique identity and request approval from the SINVO development Update Server.
- Approved installations can send heartbeats and discover authorized updates; no packages are installed automatically.

- Connected Installations now displays the configured BackOffice company name alongside the permanent installation identity.

## Software update review
- Added a dedicated BackOffice update-check screen with a non-disruptive checking overlay, changelog preview and update availability.
- Updates remain review-only until the independent installer and backup/rollback safeguards are configured.

- Attach immutable release-version and Git-revision metadata to new Staging artifacts.
- Legacy servers show their real Git revision rather than claiming the default semantic version.
- Add a separate, read-only download-and-SHA256-verification CLI for approved packages; no extraction or installation.

- Separate package preparation worker persists real downloaded-byte progress; browser can poll progress without accessing credentials.
- Installing remains disabled until independent privilege separation, backup and recovery are implemented.
