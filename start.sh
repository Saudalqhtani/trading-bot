#!/bin/bash
# تشغيل بوت التداول وبوت الأمان معاً

echo "🚀 Starting Trading Bot..."
python main_updated_final.py &

echo "🛡️ Starting Security Bot..."
python security_bot_final.py &

# انتظر حتى ينتهي أحد البوتين (لا ينتهيان أبداً)
wait
