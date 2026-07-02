import asyncio
import sys
sys.path.append("backend")
from analysis.prediction import run_prediction_pipeline
import logging
logging.basicConfig(level=logging.INFO)

async def main():
    tasks = {"test-id": {}}
    try:
        await run_prediction_pipeline("test-id", "Orcinus orca", 35.9, -5.5, "2026-07-01", 50.0, 500, tasks)
        print("Success:", tasks["test-id"])
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
