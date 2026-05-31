# DurbX

<p align="center">
  <img src="https://img.shields.io/badge/Version-0.1.0-blue.svg?style=flat-square">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square">
  <img src="https://img.shields.io/badge/Python-3.10%2B-yellow.svg?style=flat-square">
</p>

**DurbX** is an asynchronous directory discovery tool built for speed, precision, and a professional user experience. It utilizes an async request engine to identify hidden paths and sensitive files with minimal resource overhead.

---

## 📸 Terminal Preview

```text
    ____             __   _  __   DurbX v0.1.0
   / __ \__  _______/ /_ | |/ /   Advanced Directory Discovery
  / / / / / / / ___/ __ \|   /    by Harsh Zagade
 / /_/ / /_/ / /  / /_/ /   |  
/_____/\__,_/_/  /_.___/_/|_|  

Target: https://example.com | Threads: 50 | Wordlist: common.txt

14:25:45 INFO     i Starting discovery for 4613 paths...

/index.html          200   1.2KB
/admin               403   256B
/config.php          200   0B
[████████████████████] 100.0% (4613/4613) | ETA: 00:00

Finished in 12.25s. Total hits: 3
Progress: 4613 / 4613 (100.00%)
```

---

## ✨ Key Features

- 🚀 **Async Engine**: High-concurrency directory brute-forcing powered by `aiohttp`.
- 🔍 **Smart Filtering**: Show only `200 OK` responses by default for high-signal results.
- 🎨 **Modern UI**: Integrated side-by-side ASCII branding and status-based color coding.
- 🛡️ **Resource Efficient**: Bounded worker pool prevents resource exhaustion even with large wordlists.
- 🤖 **Automation Ready**: Use `-q` / `--quiet` to output only found paths for easy integration.

---

## 🚀 Installation

### Option 1: Using pipx (Recommended)
This installs DurbX in an isolated environment and makes the command available globally.
```bash
git clone https://github.com/yourusername/DurbX.git
cd DurbX
pipx install .
```

### Option 2: Using pip
```bash
pip install .
```

---

## 📖 Usage Guide

### Basic Directory Scan
Identify files and folders on a target website:
```bash
durbx -u https://example.com -w common.txt
```

### Advanced Filtering
By default, DurbX only shows `200 OK`. Use `-a` to see everything or specify codes:
```bash
# Show all hits (3xx, 4xx, 5xx) except 404
durbx -u example.com -w words.txt -a

# Only show specific status codes
durbx -u example.com -w words.txt --status 200,301,403
```

### Fast Brute-forcing
Scale up the concurrency for large wordlists:
```bash
durbx -u example.com -w big.txt -t 100
```

---

## 🛠️ Options & Flags

| Category | Option | Description |
| :--- | :--- | :--- |
| **Core** | `-u, --url` | Target URL (defaults to https://) |
| | `-w, --wordlist` | Path to wordlist file |
| | `-t, --threads` | Number of concurrent workers (default: 50) |
| **Filters** | `-a, --all` | Show all status codes [dim](except 404)[/dim] |
| | `--status` | Show only specific codes [dim](default: 200)[/dim] |
| | `--exclude` | Exclude specific codes (e.g. 404,500) |
| | `--timeout` | Request timeout in seconds (default: 3.0) |
| **Global** | `-v, --verbose` | Enable detailed query logging |
| | `-q, --quiet` | Minimal output (paths only) |
| | `-h, --help` | Show professional help menu |

---

## 📂 Project Structure

- `src/durbx/cli.py`: Command-line interface and parsing.
- `src/durbx/enumerator.py`: Async request engine and discovery logic.
- `src/durbx/utils.py`: UI utilities and professional branding.
- `src/durbx/formatter.py`: Result colorization and formatting.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Developed with ❤️ by **Harsh Zagade**
