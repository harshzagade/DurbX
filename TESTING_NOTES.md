# DurbX Testing Notes

## Bug Fixed

### Issue:
Function `should_show_result()` was missing `all_codes` parameter causing scans to hang.

### Fix Applied:
```python
def should_show_result(result, status_filter, exclude_filter, all_codes=False):
    if all_codes:
        return result.status_code != 404
    # ... rest of logic
```

## How to Test

### Create Test Server:
```bash
echo '<html><body><h1>Test</h1></body></html>' > /tmp/test.html
python3 -m http.server 8888 -d /tmp &
```

### Run DurbX:
```bash
echo "test.html
index.html
admin
login" > /tmp/wordlist.txt

durbx -u http://localhost:8888 -w /tmp/wordlist.txt -t 5
```

### Expected Results:
✅ Finds /test.html (200 OK)  
✅ Completes scan in <1 second  
✅ Progress bar displays correctly

## Test Results

- Scanned: 4 paths in 0.01 seconds ✅
- Found: 1 file (test.html) ✅
- Performance: 400 paths/second ✅

**Rating: 7/10** - Working after bug fix
