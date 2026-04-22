# DurbX

`DurbX` is an async directory enumeration tool for web targets. It takes a target URL and a wordlist, tests paths concurrently, and prints live hits as they are found.

## Features

- Async `aiohttp` request engine
- Live hit output during the scan
- Default hit filtering for `2xx` and `3xx` responses
- Status filtering with `--status`
- Status exclusion with `--exclude`
- Proxy support with `--proxy`
- Colorized output and progress bar
- Bounded worker pool for cleaner large scans and interrupts

## Installation

### Local development

```bash
git clone <your-repo-url>
cd DurbX
python3 -m pip install -e .
```

### User install

```bash
python3 -m pip install --user .
```

After installation, run:

```bash
durbx --help
```

## Usage

```bash
durbx -u https://example.com -w wordlist.txt
```

### Examples

```bash
# Basic scan
durbx -u https://example.com -w /usr/share/wordlists/dirb/common.txt

# Higher concurrency
durbx -u https://example.com -w wordlist.txt -t 100

# Show only selected codes
durbx -u https://example.com -w wordlist.txt --status 200,301,302

# Exclude selected codes
durbx -u https://example.com -w wordlist.txt --exclude 301,302

# Use a proxy
durbx -u https://example.com -w wordlist.txt --proxy http://127.0.0.1:8080
```

## Output Preview

```text
==================== DurbX ====================
      Directory Enumeration Tool
==============================================
[+] URL        : https://example.com
[+] Wordlist   : /usr/share/wordlists/dirb/common.txt
[+] Threads    : 50
[+] Total      : 4613
============================================================
/admin               200   512B       -> https://example.com/admin
/login               302   0B         -> https://example.com/login
[██████████████░░░░░░] 72.4% (3341/4613) | ETA: 00:03
============================================================
Hits: 2
Progress: 4613 / 4613 (100.00%)
============================================================
Finished
============================================================
```

## Demo

Command:

```bash
durbx -u https://example.com -w /usr/share/wordlists/dirb/common.txt -t 50
```

Sample run:

```text
==================== DurbX ====================
      Directory Enumeration Tool
==============================================
[+] URL        : https://example.com
[+] Wordlist   : /usr/share/wordlists/dirb/common.txt
[+] Threads    : 50
[+] Total      : 4613
============================================================
/admin               200   512B       -> https://example.com/admin
/login               301   0B         -> https://example.com/login
/api                 200   128B       -> https://example.com/api
[███████████████████░] 99.2% (4575/4613) | ETA: 00:00
============================================================
Hits: 3
Progress: 4613 / 4613 (100.00%)
============================================================
Finished
============================================================
```

Reusable demo text: [docs/demo.txt](/home/phishingrod/DurbX/docs/demo.txt)

## Flags

- `-u`, `--url`: target URL
- `-w`, `--wordlist`: wordlist file
- `-t`, `--threads`: concurrency level, default `50`
- `--timeout`: request timeout in seconds
- `--status`: comma-separated allowlist of status codes
- `--exclude`: comma-separated denylist of status codes
- `--proxy`: HTTP proxy URL

## Notes

- If you pass only a domain, `DurbX` uses `https://` by default.
- By default, live hits are limited to `2xx` and `3xx` responses.
- Press `Ctrl-C` to stop a scan cleanly.

## Disclaimer

Use `DurbX` only on targets you own or are explicitly authorized to test.
