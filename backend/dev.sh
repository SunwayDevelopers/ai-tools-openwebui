# CORS is left to .env (defaults to '*' for local dev — do NOT ship '*' to prod).
# Re-enable the explicit allowlist below if you want to pin dev origins instead.
# export CORS_ALLOW_ORIGIN="http://localhost:5173;http://localhost:8080"
PORT="${PORT:-8080}"
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --reload
