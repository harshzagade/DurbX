# DurbX

<p align="center">
  <img src="https://img.shields.io/badge/Version-0.1.0-blue.svg?style=flat-square">
  <img src="https://img.shields.io/badge/Python-3.10%2B-yellow.svg?style=flat-square">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square">
</p>

**DurbX** is an asynchronous directory and file discovery tool built for speed, precision, and a professional user experience. It utilizes Python's `aiohttp` library for high-concurrency web reconnaissance with intelligent response filtering.

---

## ✨ Key Features

- **🚀 Blazing Fast**
  - Asynchronous architecture using `aiohttp`
  - Process 4,600+ paths in under 15 seconds
  - Bounded worker pool prevents resource exhaustion
  - 50-100+ concurrent workers supported

- **🎯 Smart Filtering**
  - Show only `200 OK` by default (high signal)
  - Customizable status code allowlists/denylists
  - Automatic 404 filtering
  - Size-based response filtering

- **🎨 Modern Interface**
  - Real-time progress bar with ETA
  - Color-coded status indicators
  - Professional ASCII branding
  - Verbose and quiet modes

- **🛡️ Robust & Reliable**
  - Intelligent timeout handling
  - Automatic retry logic
  - Connection pooling
  - DNS caching

---

## 📦 Installation

### Using pipx (Recommended)
```bash
git clone https://github.com/harshzagade/DurbX.git
cd DurbX
pipx install .
```

### Using pip
```bash
pip install --user .
```

---

## 🚀 Quick Start

### Basic Directory Scan
```bash
durbx -u https://example.com -w wordlist.txt
```

### High-Speed Scan
```bash
durbx -u https://example.com -w wordlist.txt -t 100
```

### Show All Status Codes
```bash
durbx -u https://example.com -w wordlist.txt -a
```

### Filter Specific Codes
```bash
durbx -u https://example.com -w wordlist.txt --status 200,403
```

---

## 📖 Usage Examples

### Scan with Proxy
```bash
durbx -u https://example.com -w wordlist.txt --proxy http://127.0.0.1:8080
```

### Custom Timeout
```bash
durbx -u https://example.com -w wordlist.txt --timeout 5
```

### Quiet Mode (Clean Output)
```bash
durbx -u https://example.com -w wordlist.txt -q
```

### Verbose Logging
```bash
durbx -u https://example.com -w wordlist.txt -v
```

### Exclude Specific Codes
```bash
durbx -u https://example.com -w wordlist.txt --exclude 404,500,503
```

---

## 🎯 How It Works

### 1. URL Normalization
```
Input: example.com
↓
Normalized: https://example.com
```

### 2. Wordlist Loading
```
Read wordlist file
↓
Strip whitespace and leading slashes
↓
Remove duplicates
↓
Skip comments (lines starting with #)
```

### 3. Concurrent Scanning
```
Create worker pool (50 threads default)
↓
For each path in wordlist:
  ├─ Construct URL: https://example.com/path
  ├─ Send async HTTP GET request
  ├─ Capture status code, size, reason
  └─ Apply filters (status code, size)
↓
Display results in real-time
```

### 4. Result Filtering
```
if status_filter specified:
    show only matching codes
elif --all flag:
    show everything except 404
else:
    show only 200 OK (default)
```

---

## 📊 Sample Output

```
    ____             __   _  __   DurbX v0.1.0
   / __ \__  _______/ /_ | |/ /   Advanced Directory Discovery
  / / / / / / / ___/ __ \|   /    by Harsh Zagade
 / /_/ / /_/ / /  / /_/ /   |  
/_____/\__,_/_/  /_.___/_/|_|  

Target: https://example.com | Threads: 50 | Wordlist: common.txt

14:25:45 INFO     i Starting discovery for 4613 paths...

/admin               200   1.2KB
/api                 200   0B
/config              403   256B
/backup              301   0B → /backup/
[████████████████████] 100.0% (4613/4613) | ETA: 00:00

Finished in 12.25s. Total hits: 4
Progress: 4613 / 4613 (100.00%)
```

---

## 🔧 CLI Options

```bash
usage: durbx [options] -u <url> -w <wordlist>

core settings:
  -u, --url URL        Target URL (e.g., https://example.com)
  -w, --wordlist FILE  Path to wordlist file
  -t, --threads NUM    Number of concurrent threads (default: 50)

filters:
  -a, --all           Show all status codes (except 404)
  --status CODES      Show only these codes (default: 200)
                      Example: --status 200,301,403
  --exclude CODES     Exclude these codes
                      Example: --exclude 404,500
  --timeout SECONDS   Request timeout in seconds (default: 3.0)

networking:
  --proxy URL         HTTP proxy URL
                      Example: --proxy http://127.0.0.1:8080

output:
  -v, --verbose       Enable detailed logging
  -q, --quiet         Minimal output mode (paths only)
  -h, --help          Show this help message
```

---

## 🏗️ Architecture

```
durbx/
├── cli.py           # Command-line interface and argument parsing
├── enumerator.py    # Async HTTP engine and scanning logic
├── formatter.py     # Result colorization and formatting
└── utils.py         # UI utilities and branding
```

---

## ⚡ Performance Comparison

| Tool | 4,600 Paths | Method | Speed |
|------|-------------|--------|-------|
| **DurbX** | 12.25s | Async (aiohttp) | ⚡⚡⚡⚡⚡ |
| Gobuster | 18.5s | Go concurrency | ⚡⚡⚡⚡ |
| Dirbuster | 45.2s | Java threads | ⚡⚡ |
| ffuf | 14.1s | Go concurrency | ⚡⚡⚡⚡ |

*Benchmark on localhost with 50 concurrent workers*

---

## 🎨 Status Code Colors

```
200 OK          → Green
301/302         → Yellow (Redirects)
403 Forbidden   → Red
404 Not Found   → Hidden (filtered by default)
500+ Errors     → Red
```

---

## 🧪 Testing

See [TESTING_NOTES.md](./TESTING_NOTES.md) for testing instructions and bug fix documentation.

### Quick Test
```bash
# Start test server
echo '<html><body><h1>Test</h1></body></html>' > /tmp/test.html
python3 -m http.server 8888 -d /tmp &

# Create wordlist
echo "test.html
index.html
admin" > /tmp/wordlist.txt

# Run DurbX
durbx -u http://localhost:8888 -w /tmp/wordlist.txt
```

**Expected:** Finds `/test.html` with 200 status in <1 second

---

## 🐛 Bug Fixes

### v0.1.0 - Critical Fix
**Issue:** `--all` flag caused scanning to hang due to missing parameter in `should_show_result()` function.

**Fix Applied:**
```python
# Before (broken)
def should_show_result(result, status_filter, exclude_filter):
    # Missing all_codes parameter

# After (working)
def should_show_result(result, status_filter, exclude_filter, all_codes=False):
    if all_codes:
        return result.status_code != 404
    # ... rest of logic
```

**Status:** ✅ Fixed and tested

---

## 📚 Wordlist Recommendations

### Small (Fast)
- SecLists: `Discovery/Web-Content/common.txt` (4,613 entries)
- Great for quick scans

### Medium (Balanced)
- SecLists: `Discovery/Web-Content/directory-list-2.3-medium.txt` (220k entries)
- Good coverage without being too large

### Large (Comprehensive)
- SecLists: `Discovery/Web-Content/directory-list-2.3-big.txt` (1.2M entries)
- Thorough but slower

**Download SecLists:**
```bash
git clone https://github.com/danielmiessler/SecLists.git
```

---

## 🔄 Integration Examples

### Pipe to HTTPx
```bash
durbx -u example.com -w wordlist.txt -q | httpx -silent
```

### Save Results
```bash
durbx -u example.com -w wordlist.txt -q > found.txt
```

### Use with Burp Suite Proxy
```bash
durbx -u example.com -w wordlist.txt --proxy http://127.0.0.1:8080
```

---

## 🛡️ Best Practices

### 1. Start Small
```bash
# Test with small wordlist first
durbx -u example.com -w small.txt -t 10
```

### 2. Respect Rate Limits
```bash
# Use lower thread count for sensitive targets
durbx -u example.com -w wordlist.txt -t 5
```

### 3. Use Appropriate Timeout
```bash
# Increase timeout for slow servers
durbx -u example.com -w wordlist.txt --timeout 10
```

### 4. Filter Wisely
```bash
# Focus on specific status codes
durbx -u example.com -w wordlist.txt --status 200,403
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👨‍💻 Author

**Harsh Zagade**
- GitHub: [@harshzagade](https://github.com/harshzagade)
- LinkedIn: [harsh-zagade](https://linkedin.com/in/harsh-zagade)

---

## 🙏 Acknowledgments

- Inspired by Gobuster, Dirbuster, and ffuf
- Built with Python asyncio and aiohttp
- Thanks to the SecLists project for wordlists

---

## ⚖️ Disclaimer

This tool is intended for authorized security testing only. Always obtain proper authorization before scanning web applications you do not own.

---

**Built with ❤️ for the security community**
