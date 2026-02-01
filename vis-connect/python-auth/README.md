## Viessmann Vis-Connect (Python auth CLI)

This folder contains a small CLI script (`auth.py`) that authenticates against the Viessmann IAM endpoints, exchanges the authorization code for a token, then calls `/users/me` and prints the resulting JSON to stdout.

### Requirements

- Python 3.10+
- Dependencies from `web-form-verbrauch/requirements.txt` (includes `requests`)

### Environment variables

Set these before running:

- `VIESSMANN_CLIENT_ID`: OAuth client id
- `VIESSMANN_EMAIL`: your account email
- `VIESSMANN_PASSWORD`: your account password
- `VIESSMANN_CALLBACK_URI`: redirect/callback URI (default: `http://localhost:4200/`)
- `VIESSMANN_SCOPE`: optional (default: `IoT User`)

Optional / advanced:

- `VIESSMANN_CODE_VERIFIER`: override PKCE verifier (only if you need compatibility with an older/fixed verifier)

### Example

From the `web-form-verbrauch/` directory:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export VIESSMANN_CLIENT_ID="..."
export VIESSMANN_EMAIL="you@example.com"
export VIESSMANN_PASSWORD="..."
export VIESSMANN_CALLBACK_URI="http://localhost:4200/"

python vis-connect/python-auth/auth.py --pretty
```

### Notes

- **SSL verification**: the legacy PHP script disables SSL verification; the Python CLI keeps verification **enabled by default**. If you must disable it temporarily (not recommended), use `--insecure-skip-ssl-verify`.
- **Output**: the script prints the `/users/me` JSON to stdout, similar to the PHP script’s `echo($response)`.
