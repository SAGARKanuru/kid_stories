"""One-time helper: run on YOUR computer to get the YouTube refresh token for GitHub secrets.

    pip install google-auth-oauthlib
    python tools/get_youtube_token.py path/to/client_secret.json

A browser opens; sign in with the Google account that owns the channel and allow access.
Then copy the three printed values into GitHub -> Settings -> Secrets and variables -> Actions.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]

if len(sys.argv) != 2:
    sys.exit(__doc__)
secrets = json.load(open(sys.argv[1]))
flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = secrets.get("installed") or secrets.get("web")
print("\nAdd these as GitHub Actions secrets:\n")
print(f"YT_CLIENT_ID      = {info['client_id']}")
print(f"YT_CLIENT_SECRET  = {info['client_secret']}")
print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
