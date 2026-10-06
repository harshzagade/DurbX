# Changelog

All notable changes to DurbX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- `assets/screenshots/`: real terminal captures — `01-help.png` (help screen)
  and `02-live-scan.png` (scan against a local `http.server` test instance).
  Both were recorded from actual runs, not mockups.
- `CHANGELOG.md` to track release history.

### Changed
- README rewritten around verified facts only: every usage example was checked
  against `durbx --help`, and the sample output is a real localhost run.
- Removed unverified benchmark claims (third-party tool timing comparisons).
- Feature list corrected to match the code (e.g. graceful per-request error
  handling instead of "automatic retry logic").

## [0.1.0] - 2026-06-01

### Added
- Initial professional release: async directory/file discovery over `aiohttp`.
- CLI: `-u/--url`, `-w/--wordlist`, `-t/--threads` (default 50),
  `-a/--all`, `--status`, `--exclude`, `--timeout` (default 3.0s),
  `--proxy`, `-v/--verbose`, `-q/--quiet`.
- Status-code filtering: show only `200` by default, `--all` shows everything
  except 404, `--status` allowlist / `--exclude` denylist.
- Bounded `TCPConnector` worker pool with 300s DNS cache.
- Live progress bar with ETA, color-coded results, ASCII banner branding.
- Wordlist handling: whitespace/leading-slash stripping, dedup, `#` comments.
- URL normalization (`example.com` → `https://example.com`).
- Unit test suite (`tests/test_core.py`): URL normalization, wordlist parsing,
  status-code parsing, filtering, formatting, CLI flags.
- `TESTING_NOTES.md` with manual localhost test procedure.

### Fixed
- `--all` flag hanging: `should_show_result()` was missing the `all_codes`
  parameter (`ee4c627`).

[Unreleased]: https://github.com/harshzagade/DurbX/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/harshzagade/DurbX/releases/tag/v0.1.0
