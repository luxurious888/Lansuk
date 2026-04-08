#!/bin/bash
cd /workspaces/Lansuk
source .venv/bin/activate

echo "🚀 Starting Lan Sook POS..."

# รัน uvicorn background
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
echo "✅ Server PID: $SERVER_PID"

# รอ server start
sleep 3

# รัน bot background  
python3 run_bot.py &
BOT_PID=$!
echo "✅ Bot PID: $BOT_PID"

echo ""
echo "🌐 Manager: https://psychic-space-bassoon-749p44vpvwgcpv7r-8000.app.github.dev/manager.html"
echo "🍳 KDS:     https://psychic-space-bassoon-749p44vpvwgcpv7r-8000.app.github.dev/kds.html"
echo "📖 Docs:    https://psychic-space-bassoon-749p44vpvwgcpv7r-8000.app.github.dev/docs"
echo ""
echo "กด Ctrl+C เพื่อหยุดทั้งหมด"

wait
