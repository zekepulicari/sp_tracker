import os
from dotenv import load_dotenv

# Load environment variables from .env file at the project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DEFAULT_ZOOM_THRESHOLD = int(os.getenv("DEFAULT_ZOOM_THRESHOLD", "6"))
INATURALIST_API = os.getenv("INATURALIST_API", "")
TAXON_ID = int(os.getenv("TAXON_ID", "41521")) # Orcinus orca
GEMINI_KEY = os.getenv("GEMINI_KEY", "")
