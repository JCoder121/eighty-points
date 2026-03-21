#!/bin/bash
# Start uvicorn + ngrok and print a QR code for mobile testing.

set -e

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$UVICORN_PID" "$NGROK_PID" 2>/dev/null
  wait "$UVICORN_PID" "$NGROK_PID" 2>/dev/null
  echo "Done."
  exit 0
}

# Start uvicorn in the background
echo "Starting uvicorn..."
uvicorn shengji.network.app:app --reload &
UVICORN_PID=$!

# Give it a moment to bind
sleep 2

# Start ngrok in the background
echo "Starting ngrok..."
ngrok http 8000 &
NGROK_PID=$!

trap cleanup INT TERM

# Wait for ngrok to be ready
sleep 3

# Fetch the public URL from ngrok's local API
URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data['tunnels']:
    if t['proto'] == 'https':
        print(t['public_url'])
        break
")

if [ -z "$URL" ]; then
  echo "Could not get ngrok URL. Check http://localhost:4040 manually."
else
  echo ""
  echo "Game URL: $URL"
  echo ""
  qrencode -t PNG -o /tmp/eighty_qr.png "$URL"
  open /tmp/eighty_qr.png
fi

# Keep running until Ctrl+C
echo "Press Ctrl+C to stop."
wait
