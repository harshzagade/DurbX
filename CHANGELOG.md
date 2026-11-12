# Changelog

All notable changes to DurbX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- `--sort`: sort hits by path (case-insensitive, per target) in `-o`/`--json`/
  `--jsonl`/`--csv` output instead of worker completion order, so repeated
  runs diff cleanly. `sort_hits_by_path()` in formatter.py; the live
  terminal lines still print in completion order. 8 new unit tests.
- `--jsonl FILE`: JSON Lines report (one JSON object per hit) alongside
  `--json`, for streaming pipelines. `render_jsonl_report()` in formatter.py
  shares the per-hit dict with the JSON report via `_hit_to_dict()`, so both
  outputs always carry the same fields; no `stats` block. An unwritable
  path fails fast with exit 2. 7 new unit tests.
- `--no-color`: disable ANSI colors in terminal output (banner, hit lines,
  summary) without suppressing any output the way `-q` does, for clean
  piped logs. `format_result()` / `render_results()` take a `color=False`
  flag (the plain line is byte-identical to the `-o` output), and
  `utils.set_no_color()` swaps the shared rich console for a no-color one
  (also honored by `--help`). 9 new unit tests; the conftest rich stub
  Console now accepts constructor kwargs and records `no_color`.
- `--retry-on CODES`: retry 500/502/503 (or user-given codes, ranges like
  `500-599` accepted) with the same exponential backoff and `Retry-After`
  handling as 429, instead of only retrying 429. `fetch_with_retry()` takes
  a `retry_on` tuple (default `(429,)`), threaded through
  `detect_wildcard()` and `enumerate_directories()`; the CLI parses it with
  the existing status-code list grammar (bad codes fail fast with exit 2).
  10 new unit tests.
- `--csv FILE`: CSV report (one row per hit) alongside `--json`, for
  spreadsheet pipelines. `render_csv_report()` in formatter.py carries the
  same per-hit fields as the JSON report (target, path, URL, status, reason,
  size, attempts, directory listing, redirect target, duplicate count,
  latency); the `csv` module quotes fields containing commas, quotes, or
  newlines so they round-trip exactly, and the header row is always written
  even with no hits. An unwritable path fails fast with exit 2.
  6 new unit tests.
- `--exclude-path REGEX`: repeatable flag to skip wordlist entries matching a
  regex before any request is sent, for cutting noisy subtrees (e.g.
  `--exclude-path '^assets/'`). Matching is against the entry as written in
  the wordlist, before `-x` extension expansion, so one pattern drops the
  whole subtree including its variants; the skipped count is reported
  (`Excluded N wordlist entries via --exclude-path.`). `parse_exclude_paths()`
  / `filter_excluded_paths()` in enumerator.py; empty or uncompilable
  patterns fail fast with exit 2, and excluding every entry fails fast too.
  7 new unit tests.
- Tech-header summary: `Server` and `X-Powered-By` values seen across
  displayed hits are counted per value and reported in the final summary
  (`Tech headers: Server: nginx/1.18 (2), Apache (1); X-Powered-By:
  PHP/8.1 (1)`), and carried as `stats.tech_headers` in `--json`
  reports. Only rows that pass the display filters are counted, so
  filtered-out responses never contribute. 6 new unit tests.
- Body-hash dedupe: 200 responses whose first 8 KB hash identically
  (SHA-256, computed from the same single read that feeds directory-listing
  detection) collapse into one representative row with an
  `(xN identical bodies)` count in terminal and `-o` output, a
  `duplicate_count` field on `--json` hits, and a
  `duplicate_bodies_collapsed` stats count plus a
  `(N duplicate body(s) collapsed)` note in the final summary — for
  template-duplicate pages the wildcard filter cannot catch (same size is
  not required, same first-8KB hash is). Only displayed 200 hits seed the
  map; non-200s, hashless bodies (empty bodies, HEAD responses, responses
  without a body reader) are never collapsed, and bodies differing only
  past 8 KB still collapse (documented). 8 new unit tests.
- Per-status breakdown in the final summary: hit counts per status code
  (`by status: 200: 3, 403: 1`) instead of only a total, aggregated
  across targets for multi-target runs; `--json` reports carry the same
  breakdown as `stats.status_counts`. Only displayed hits are counted —
  wildcard-filtered rows and failed requests never appear. 6 new unit
  tests.
- Request latency: every hit records its wall-clock request time in
  milliseconds (retries and their backoff included); the final summary
  prints the average plus the 3 slowest hits, and `--json` reports carry
  `avg_latency_ms`, `slowest_hits`, and per-hit `latency_ms`. Hits built
  without a measurement (e.g. older code paths) report `null` and are
  excluded from the averages. 6 new unit tests (one existing exact-dict
  JSON test updated for the new hit field).
- Redirect-target capture: 3xx hits now record the response's `Location`
  header, so terminal/`-o` output shows `-> <destination>` instead of
  repeating the requested URL (which said nothing about where the
  redirect goes); other 3xx codes (303/307/308) gain the suffix too, and
  `--json` hits carry a `redirect_target` field (null when absent).
  Hits without a captured target keep the old `-> <url>` suffix.
  6 new unit tests.
- `--random-agent`: rotate the User-Agent per scan request from a small
  built-in list of common browser agents (Chrome/Firefox/Safari/Edge on
  Windows, macOS, and Linux), round-robin so scans stay reproducible.
  Overrides `--user-agent` for scan requests; an explicit `-H User-Agent`
  header still wins (existing precedence), and the soft-404 probe keeps
  the session agent. 7 new unit tests.
- Directory-listing detection: 200 responses whose first 8 KB look like a
  server autoindex page (`<title>`/`<h1>` "Index of /..." markers, as used
  by Apache/nginx/lighttpd) are flagged `(directory listing)` in terminal
  and `-o` output, carried as `directory_listing` in `--json` hits and a
  `directory_listings` stats count, and tallied in the final summary.
  Detection reads only the first 8 KB, is off for the wildcard probe, and
  fails open when a response exposes no body reader. 6 new unit tests.
- `--append` for `-o/--output`: append hits to the output file instead of
  overwriting it, for accumulating results across multiple runs.
  `--append` without `-o` fails fast with exit 2, and appending to a file
  whose last line has no trailing newline inserts a separator first so
  the first new hit never glues onto the previous line. 5 new unit tests.
- Retry attempts recorded on `ScanResult`: `fetch_with_retry()` already
  counted attempts, but `scan()` dropped them — hits now carry
  `attempts` (default 1, so existing constructions are unaffected) and
  hits that needed 429 retries show `(retried N)` in terminal output,
  `-o` plain output, and the `--json` report (`attempts` field), so
  rate-limit pressure is visible instead of silent. 4 new unit tests.
- Status-code ranges in `--status`/`--exclude`: `parse_status_codes()`
  now accepts inclusive ranges alongside single codes
  (e.g. `--status 200,301,500-599`), expanded in order and deduplicated;
  malformed tokens, reversed ranges, and endpoints outside 100-599 fail
  fast with exit 2. 7 new unit tests.
- HTTP-date form of `Retry-After`: `parse_retry_after()` now honors RFC 9110
  HTTP-dates alongside delta-seconds (converted to seconds-from-now, past
  dates retry immediately, still clamped to the 60s maximum); previously
  the date form was ignored and fell back to exponential backoff.
  The old test asserting the date form returned `None` was updated, and
  2 new tests cover parsing plus an end-to-end 429 retry.
- `--rate-limit RPS`: global requests-per-second throttle via a token bucket
  shared across all workers (`RateLimiter` in enumerator.py; bucket holds one
  second's worth of tokens, refills continuously). Complements the per-worker
  `--delay` pause for targets with strict global rate limits; non-positive
  values fail fast with exit 2. 6 new unit tests.
- `--stdin` path input: read candidate paths from stdin instead of a wordlist
  file, so DurbX pipes cleanly from other recon tools
  (`other-tool | durbx -u example.com --stdin`); `-w -` is an alias for the
  same source. Shared `parse_wordlist_lines()` normalization means stdin and
  file inputs behave identically (blanks, `#` comments, duplicates dropped);
  `-w/--wordlist` is no longer argparse-required, and `--stdin` combined with
  a real `-w` file fails fast with exit 2. 9 new unit tests.
- `--match-length N`: inverse of `--filter-length` — show ONLY responses whose
  body size equals N (comma-separated for several sizes), for zeroing in on a
  known interesting size. `parse_match_lengths()` shares the size-list grammar
  and fail-fast validation of `parse_filter_lengths()`; the allowlist is
  checked before the `--all` default rule and combined (AND) with the status
  filters and `--filter-length`; threaded through `enumerate_directories()`
  and `render_results()`. 8 new unit tests.
- `--checkpoint FILE` + `--resume FILE`: resume support for interrupted
  scans (single-target only). `--checkpoint` writes progress checkpoints
  (target, full expanded entry list, completed entries, finished flag) at scan
  start, at most every 10s during the scan, and at completion — via a temp
  file + rename so a kill can never leave a corrupt checkpoint, and a failed
  write warns once without killing the scan. `--resume` continues where the
  scan stopped: already-scanned entries are skipped, scan stats count the
  whole original scan, and progress is written back to the checkpoint file.
  `--resume` fails fast (exit 2) on a missing/corrupt checkpoint, a
  finished scan, a `-u` target or wordlist/extensions that no longer match
  the checkpoint, and on combination with `--targets` (ditto `--checkpoint`).
  `write_checkpoint()`/`load_checkpoint()` in enumerator.py with versioned
  payload validation. 10 new unit tests.
- `--json FILE`: machine-readable final report for pipelines — writes a JSON
  document with a `stats` block (targets, completed/total counts, hit count,
  wildcard-filtered count, duration) plus every hit (target, path, URL, status
  code, reason, size). Works with single-target and `--targets` multi-target
  runs; an unwritable path fails fast with exit 2.
  4 new unit tests.
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
