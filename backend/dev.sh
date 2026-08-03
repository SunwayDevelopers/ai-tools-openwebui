# CORS is left to .env (defaults to '*' for local dev — do NOT ship '*' to prod).
# Re-enable the explicit allowlist below if you want to pin dev origins instead.
# export CORS_ALLOW_ORIGIN="http://localhost:5173;http://localhost:8080"
PORT="${PORT:-8080}"
# --ws wsproto (Sunway): the `websockets` legacy impl uvicorn[standard] picks by default
# drops the socket during long/idle tool calls, leaving the chat spinner hanging even though
# the response completed. Keep in sync with backend/start.sh and dev.ps1.
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --ws wsproto --reload
