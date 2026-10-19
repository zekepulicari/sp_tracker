"""Bounded in-process job queue for a single-worker portfolio deployment."""
import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)

class BusyError(ValueError):
    pass

class Jobs:
    def __init__(self, active=2, queued=8, retention=86400):
        self.queue = asyncio.Queue(maxsize=queued)
        self.active_limit = active
        self.retention = retention
        self.records = {}
        self.workers = []

    async def start(self):
        self.workers = [asyncio.create_task(self.worker()) for _ in range(self.active_limit)]

    async def stop(self):
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    def prune(self):
        now = time.monotonic()
        for task_id, task in list(self.records.items()):
            finished = task.get('finished')
            if finished is None:
                continue
            if now - finished >= self.retention + 3600:
                del self.records[task_id]
            elif now - finished >= self.retention:
                task.update(status='expired', results=None, error=None, progress='This task has expired. Run it again.')

    def submit(self, runner):
        self.prune()
        if self.queue.full() or len(self.records) >= 1000:
            raise BusyError('The analysis queue is busy. Please try again shortly.')
        task_id = str(uuid.uuid4())
        self.records[task_id] = {'status': 'queued', 'progress': 'Waiting for an analysis slot…',
                                 'results': None, 'error': None}
        self.queue.put_nowait((task_id, runner))
        return task_id

    def get(self, task_id):
        self.prune()
        return self.records.get(task_id)

    async def worker(self):
        while True:
            task_id, runner = await self.queue.get()
            task = self.records[task_id]
            task['status'] = 'running'
            def progress(message):
                task['progress'] = message
            try:
                task['results'] = await asyncio.wait_for(runner(progress), timeout=1200)
                task.update(status='complete', progress='Complete')
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                task.update(status='failed', error='Analysis timed out. Reduce the sample size or area and retry.')
            except ValueError as exc:
                task.update(status='failed', error=str(exc))
            except Exception:
                logger.exception('Analysis failed')
                task.update(status='failed', error='Analysis could not be completed. Please try again.')
            finally:
                task['finished'] = time.monotonic()
                self.queue.task_done()
                # A runner can close over a request credential; release it before waiting.
                runner = None
