"""Temporary AT SDK debug probe. Delete after use."""
import os
import sys

print("== CA-bundle env vars ==")
for k in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR"):
    print(f"  {k}: {os.environ.get(k, '<unset>')}")
print()

import africastalking
import requests
import urllib3
import ssl
import httpx
import certifi

print("== Versions ==")
print(f"  requests: {requests.__version__}  urllib3: {urllib3.__version__}")
print(f"  httpx:    {httpx.__version__}    certifi: {certifi.__version__}")
print(f"  openssl:  {ssl.OPENSSL_VERSION}")
print(f"  certifi bundle: {certifi.where()}")
print()

username = os.environ.get("AT_USERNAME", "sandbox")
api_key = os.environ.get("AT_API_KEY", "")
url = "https://api.sandbox.africastalking.com/version1/user"
hdr = {"apiKey": api_key, "Accept": "application/json"}
prm = {"username": username}

# 1. httpx (known-working for your other services)
print("== httpx call ==")
try:
    r = httpx.get(url, params=prm, headers=hdr, timeout=15)
    print(f"  OK status={r.status_code} body={r.text[:180]!r}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
print()

# 2. requests with default (certifi) bundle
print("== requests (default certifi) ==")
try:
    r = requests.get(url, params=prm, headers=hdr, timeout=15)
    print(f"  OK status={r.status_code} body={r.text[:180]!r}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
print()

# 3. requests with system cert store
print("== requests (verify=False) ==")
import warnings
warnings.filterwarnings("ignore")
try:
    r = requests.get(url, params=prm, headers=hdr, timeout=15, verify=False)
    print(f"  OK status={r.status_code} body={r.text[:180]!r}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
