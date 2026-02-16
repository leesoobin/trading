import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


def is_kis_domestic_open() -> bool:
    """KIS 국내 장 운영 시간: 평일 09:00-15:20 KST"""
    now = datetime.now(KST)
    if now.weekday() >= 5:  # 토요일(5), 일요일(6)
        return False
    market_open = time(9, 0)
    market_close = time(15, 20)
    current_time = now.time()
    return market_open <= current_time <= market_close


def is_kis_overseas_open(summer_time: bool = False) -> bool:
    """KIS 해외(미국) 장 운영 시간
    - 서머타임: 22:30-05:00 KST (EDT, UTC-4)
    - 겨울타임: 23:30-06:00 KST (EST, UTC-5)
    """
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    if summer_time:
        open_time = time(22, 30)
    else:
        open_time = time(23, 30)
    close_time = time(6, 0)
    # 자정 걸침 처리
    if open_time > close_time:
        return current_time >= open_time or current_time <= close_time
    return open_time <= current_time <= close_time


class BotScheduler:
    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone=KST)

    def add_upbit_job(self, func, interval_seconds: int = 60):
        """업비트: 매 N초마다 전략 체크 (24/7)"""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id="upbit_strategy",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"업비트 스케줄 등록: {interval_seconds}초 간격")

    def add_kis_domestic_job(self, func, interval_seconds: int = 60):
        """KIS 국내: 평일 09:00-15:20 KST 사이에만 실행"""
        async def _guarded():
            if is_kis_domestic_open():
                await func()
        self._scheduler.add_job(
            _guarded,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id="kis_domestic_strategy",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"KIS 국내 스케줄 등록: {interval_seconds}초 간격 (09:00-15:20)")

    def add_kis_overseas_job(self, func, interval_seconds: int = 60):
        """KIS 해외: 평일 22:30-05:00 KST (서머타임 기준)"""
        async def _guarded():
            if is_kis_overseas_open():
                await func()
        self._scheduler.add_job(
            _guarded,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id="kis_overseas_strategy",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"KIS 해외 스케줄 등록: {interval_seconds}초 간격 (22:30-05:00)")

    def add_daily_report_job(self, func):
        """일일 리포트: 매일 16:00 KST"""
        self._scheduler.add_job(
            func,
            trigger=CronTrigger(hour=16, minute=0, timezone=KST),
            id="daily_report",
            replace_existing=True,
        )
        logger.info("일일 리포트 스케줄 등록: 매일 16:00 KST")

    def add_daily_reset_job(self, func):
        """일일 손익 리셋: 매일 00:00 KST"""
        self._scheduler.add_job(
            func,
            trigger=CronTrigger(hour=0, minute=0, timezone=KST),
            id="daily_reset",
            replace_existing=True,
        )

    def start(self):
        self._scheduler.start()
        logger.info("스케줄러 시작")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        logger.info("스케줄러 중지")
