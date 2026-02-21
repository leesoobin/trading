#!/bin/bash
# AutoTrade Bot 시작 스크립트

cd "$(dirname "$0")"

echo "=== AutoTrade Bot 시작 ==="

# 기존 프로세스 종료
PIDS=$(lsof -ti :8080 2>/dev/null)
if [ -n "$PIDS" ]; then
  echo "기존 프로세스 종료: PID $PIDS"
  echo "$PIDS" | xargs kill -9 2>/dev/null
  sleep 1
fi

# bot.lock 정리
if [ -f bot.lock ]; then
  echo "bot.lock 제거"
  rm -f bot.lock
fi

# 로그 디렉토리 생성
mkdir -p logs

# 백그라운드 실행 (오늘 날짜 로그 파일)
LOG="logs/bot_$(date +%Y%m%d_%H%M).log"
nohup .venv/bin/python main.py >> "$LOG" 2>&1 &
BOT_PID=$!

echo "봇 시작됨 (PID: $BOT_PID)"
echo "로그: $LOG"
echo "대시보드: http://localhost:8080"
echo ""
echo "로그 보기:  tail -f $LOG"
echo "봇 종료:    kill $BOT_PID"
