import os
from dotenv import load_dotenv
from core.library.delta_rest_client import DeltaRestClient


class DeltaExchangeSource:
    def __init__(self):
        # Load .env file
        load_dotenv()

        base_url = os.getenv("DELTA_BASE_URL")
        api_key = os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DELTA_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("Delta API credentials not found in environment variables")

        self.client = DeltaRestClient(
            base_url=base_url, api_key=api_key, api_secret=api_secret
        )
