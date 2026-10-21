# Changelog

All notable changes to DurbX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- `--targets FILE`: scan multiple base URLs from a file, one per line (use
  instead of `-u/--url`, which is no longer required; the two are mutually
  exclusive). Blank lines and `#` comments are skipped, targets are normalized
  (`example.com` -> `https://example.com`) and deduped; each target is scanned
  sequentially with its own wildcard probe and per-target progress, and `-o`
  output groups hits under `# Target: <url>` section headers. A missing file,
  an empty file, or an invalid line all fail fast with exit 2.
  7 new unit tests.
- `--filter-length N`: hide responses whose body size equals N (gobuster-style),
  for cutting through identical-size noise. Comma-separated for several sizes
  (`--filter-length 1234,5678`); `parse_filter_lengths()` fails fast with exit
  2 on non-integer or negative values; the filter is checked before the `--all`
  default rule so an explicit user filter always wins; `render_results()` also
  honors it. 7 new unit tests.
- `-m/--method METHOD`: choose the HTTP request method instead of hard-coded
  GET — one of `GET` (default), `HEAD`, `POST`. `fetch_with_retry()` now
  dispatches via `session.request(method, ...)`, and `parse_method()`
  normalizes case and fails fast with exit 2 on unknown verbs.
  6 new unit tests.
- `--follow-redirects`: follow 3xx redirects instead of the hard-coded
  `allow_redirects=False`. `enumerate_directories(follow_redirects=...)`
  threads the policy through `fetch_with_retry()` and `detect_wildcard()`
  so the soft-404 fingerprint matches what the scan actually sees.
  3 new unit tests.
### Fixed
- TTY color bug: on color terminals, scan result lines rendered mangled
  output like literal `ESC[1m[ESC[0m32m` because rich's `ReprHighlighter`
  was splitting colorama's ANSI escapes when highlighting numbers inside
  them. The result-line `console.print()` in `cli.py` now passes
  `highlight=False`; output renders as clean colorama colors again.

### Added
- `-H/--header` repeatable flag: send custom HTTP headers (auth cookies,
  tokens) with every request. `parse_headers()` validates the `Name: value`
  form (RFC 9110 token names; values may contain colons) and fails fast
  with exit 2 on malformed input; headers merge into the session and take
  precedence over `--user-agent` (curl parity). 12 new unit tests.
- Wildcard/soft-404 detection: before the scan, a random unguessable path
  (`durbx-wildcard-<hex>`) is probed and its (status, body size) recorded as
  a fingerprint; scan results indistinguishable from it are auto-filtered as
  wildcard noise and counted in the summary
  (`(N hidden by wildcard filter)`). Enabled by default; `--no-wildcard`
  disables it. Probe failure fails open (no filtering). `WildcardFingerprint`
  / `detect_wildcard()` / `is_wildcard_match()` in `enumerator.py`,
  `ScanSummary` gains `wildcard_filtered` + `fingerprint`; 10 new unit tests.
- `--delay SECONDS`: per-worker pause between requests for stealthy scans
  against rate-limited targets (default 0; negative values fail fast with
  exit 2). 4 new unit tests (CLI parsing, negative-value rejection,
  recorded inter-request sleeps, zero-delay no-op).
- `--user-agent UA`: override the hard-coded `DurbX/0.1` User-Agent header
  (empty values fail fast with exit 2). 4 new unit tests (CLI parsing,
  empty-value rejection, default and custom header wiring).
- `-o/--output FILE`: save discovered hits to a file as plain uncolored lines
  (path, code, size, redirect target). Write errors exit 2 instead of
  crashing mid-run. `plain_result_line()` / `render_plain_results()` in
  `formatter.py`, 5 new unit tests.
- `-x/--extensions` flag: probe file extensions for every wordlist entry
  (e.g. `-x php,html` requests `/admin`, `/admin.php`, `/admin.html`).
  Bare entries come first, directory guesses (`trailing/`) get no extension
  variants, duplicates are dropped, and malformed tokens (empty, containing
  `/` or whitespace) fail fast. `parse_extensions()` / `expand_extensions()`
  in `enumerator.py`, plus 7 new unit tests.
- Backoff + retry on HTTP 429 responses: new `--retries` flag (default 3;
  `0` disables). Requests that hit rate limiting are retried with
  exponential backoff (1s, 2s, 4s, ...) unless the server's `Retry-After`
  header names a delay (clamped to 60s, HTTP-date form ignored).
  `FetchOutcome` / `fetch_with_retry()` in `enumerator.py`, plus 11 new
  unit tests (backoff, Retry-After parsing, retry-then-succeed, give-up
  after max retries, zero-retries disabled, error propagation).
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
