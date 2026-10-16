"""Shared, process-wide upstream budgets. No credentials in URLs or errors."""
import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone
import time
from urllib.parse import urlparse
import httpx
from config import UPSTREAM_DAILY_BUDGET

class UpstreamError(ValueError):
    pass

class Budget:
    def __init__(self, daily=UPSTREAM_DAILY_BUDGET):
        self.daily = daily
        self.days = defaultdict(lambda: [None, 0])
        self.minutes = defaultdict(deque)

    def reserve(self, host, now=None):
        now = time.monotonic() if now is None else now
        day = datetime.now(timezone.utc).date().isoformat()
        if self.days[host][0] != day:
            self.days[host] = [day, 0]
        if self.days[host][1] >= self.daily:
            raise UpstreamError('Daily data-service budget reached. Please try tomorrow.')
        queue = self.minutes[host]
        while queue and now - queue[0] >= 60:
            queue.popleft()
        per_minute = 50 if 'inaturalist' in host else 400
        if len(queue) >= per_minute:
            return 60 - (now - queue[0])
        queue.append(now)
        self.days[host][1] += 1
        return 0

class Gateway:
    def __init__(self):
        self.budget = Budget()
        self.semaphore = asyncio.Semaphore(4)
        self.client = None

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        self.semaphore = asyncio.Semaphore(4)

    async def get(self, url, params=None):
        host = urlparse(url).hostname
        for attempt in range(3):
            async with self.semaphore:
                wait = self.budget.reserve(host)
                while wait:
                    await asyncio.sleep(wait)
                    wait = self.budget.reserve(host)
                try:
                    if self.client is None:
                        self.client = httpx.AsyncClient(timeout=30)
                    response = await self.client.get(url, params=params)
                    if 'scheduled maintenance' in response.text[:10000].lower():
                        raise UpstreamError('iNaturalist is undergoing scheduled maintenance. Please try again after the service returns.')
                    if response.status_code == 429:
                        raise UpstreamError('Data-service quota reached. Try again later or reduce the sample size.')
                    if response.status_code >= 500 and attempt < 2:
                        pass
                    else:
                        response.raise_for_status()
                        return response.json()
                except UpstreamError:
                    raise
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 2:
                        raise UpstreamError('The data service did not respond. Please try again later.') from None
                except httpx.HTTPStatusError as exc:
                    raise UpstreamError(f'The data service returned HTTP {exc.response.status_code}. Please try again later.') from None
                except ValueError:
                    raise UpstreamError('The data service returned an incomplete response. Please try again later.') from None
            await asyncio.sleep(2 ** attempt)
        raise UpstreamError('The data service is temporarily unavailable.')

gateway = Gateway()
