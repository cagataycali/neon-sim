#!/usr/bin/env bash
# View the Isaac Sim live stream from Thor
# Usage: ./view_thor_stream.sh [host] [port]

HOST="${1:-192.168.1.151}"
PORT="${2:-9999}"

echo "🎥 Viewing Isaac Sim stream from ${HOST}:${PORT}"
echo "   Press Q or close the window to stop."
echo

if command -v ffplay >/dev/null 2>&1; then
    exec ffplay -hide_banner \
        -fflags nobuffer \
        -flags low_delay \
        -probesize 32 \
        -analyzeduration 0 \
        -window_title "🦆 Thor Isaac Sim — ${HOST}:${PORT}" \
        -i "tcp://${HOST}:${PORT}"
elif command -v vlc >/dev/null 2>&1; then
    exec vlc "tcp://${HOST}:${PORT}"
elif command -v mpv >/dev/null 2>&1; then
    exec mpv --profile=low-latency "tcp://${HOST}:${PORT}"
else
    echo "❌ No video player found. Install one:"
    echo "   brew install ffmpeg   # provides ffplay"
    echo "   brew install mpv"
    echo "   brew install --cask vlc"
    exit 1
fi
