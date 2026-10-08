"""追更：后台定时检查开启 follow 的任务，只下记录里没有的新集。"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("hg-dl.follow")

# 默认每小时看一眼；同一任务至少隔 20h 再查（近似每天）
_POLL_SEC = 3600
_MIN_GAP_SEC = 20 * 3600

_stop = threading.Event()
_thread: threading.Thread | None = None


def start_follow_loop() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="hg-follow", daemon=True)
    _thread.start()


def stop_follow_loop() -> None:
    _stop.set()


def _loop() -> None:
    # 启动后稍等，避免和 lifespan 抢资源
    if _stop.wait(45):
        return
    while not _stop.is_set():
        try:
            _tick()
        except Exception:  # noqa: BLE001
            log.exception("follow tick failed")
        if _stop.wait(_POLL_SEC):
            break


def _tick() -> None:
    from .downloads import check_follow_tasks

    res = check_follow_tasks(min_gap=_MIN_GAP_SEC)
    if not res.get("checked"):
        return
    log.info(
        "follow check checked=%s enqueued=%s started=%s errors=%s",
        res.get("checked"),
        res.get("enqueued"),
        res.get("started"),
        res.get("errors"),
    )
