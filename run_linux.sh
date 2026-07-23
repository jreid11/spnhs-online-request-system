#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
exec waitress-serve --listen=0.0.0.0:5000 app:app
