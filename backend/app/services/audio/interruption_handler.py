import asyncio
from typing import Optional
from app.utils.logger import logger

class InterruptionHandler:
    def __init__(self):
        self.is_ai_speaking = False
        self.current_task: Optional[asyncio.Task] = None

    def start_speaking(self, task: Optional[asyncio.Task] = None):
        self.is_ai_speaking = True
        self.current_task = task

    def stop_speaking(self):
        self.is_ai_speaking = False
        self.current_task = None

    def handle_customer_speech_detected(self) -> bool:
        """
        Returns True if an active AI playback was interrupted.
        Cancels the active AI generation task if still running.
        """
        if self.is_ai_speaking:
            logger.info("[InterruptionHandler] Customer interrupted AI speech. Triggering cancellation.")
            self.is_ai_speaking = False
            if self.current_task and not self.current_task.done():
                self.current_task.cancel()
                self.current_task = None
            return True
        return False
