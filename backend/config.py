"""Environment variables take precedence over the project root .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DEFAULT_ZOOM_THRESHOLD = int(os.getenv('DEFAULT_ZOOM_THRESHOLD', '6'))
TAXON_ID = 41521
GEMINI_KEY = os.getenv('GEMINI_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite')
ALLOWED_ORIGINS = [s.strip() for s in os.getenv('ALLOWED_ORIGINS', '').split(',') if s.strip()]
DISCOVERY_CAP = int(os.getenv('DISCOVERY_CAP', '5000'))
UPSTREAM_DAILY_BUDGET = int(os.getenv('UPSTREAM_DAILY_BUDGET', '6000'))
MODEL_VERSION = '2.2.0'
