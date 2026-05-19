import requests
session = requests.Session()

# Check homepage loads
r = session.get('http://127.0.0.1:8000/', timeout=10)
print("Home page status:", r.status_code)

# Check for critical components
checks = {
    'sb-nav-content': 'id="sb-nav-content"' in r.text,
    'buildSidebar': 'function buildSidebar()' in r.text,
    'debugSidebar': 'window.debugSidebar' in r.text,
    'NAV object': 'const NAV = {' in r.text,
    'error handling': '[ERROR]' in r.text and '[DEBUG]' in r.text,
}

print("\nFrontend components:")
for name, present in checks.items():
    print(f"  {name}: {'YES' if present else 'NO'}")

if all(checks.values()):
    print("\nSUCCESS: All components present - menu should work!")
else:
    print("\nWARNING: Some components missing")
