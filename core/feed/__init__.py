"""
Real-time data feed from Dhan (single source of truth).
"""

from core.feed.dhan_websocket import create_instruments, run_feed, main_loop

__all__ = ["create_instruments", "run_feed", "main_loop"]
