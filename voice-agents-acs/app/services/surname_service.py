"""
Surname Verification Service
Wrapper around surname_verifier.py with Azure Blob integration
"""
import os
import logging
import asyncio
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


class SurnameService:
    """Manages surname verification with phonetic matching"""

    def __init__(self, config: dict):
        self.blob_connection_string = config.get("AZURE_STORAGE_CONNECTION_STRING")
        self.data_container = config.get("DATA_CONTAINER_NAME", "agent-data")
        self.db_path = "data/surnames.db"

        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)

        # Download surnames.db from blob if not exists
        if not os.path.exists(self.db_path):
            logger.info("📥 Downloading surnames.db from Azure Blob Storage...")
            self._download_surnames_db()
        else:
            logger.info(f"✅ surnames.db already exists at {self.db_path}")

    def _download_surnames_db(self):
        """Download surnames.db from Azure Blob Storage"""
        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                self.blob_connection_string
            )
            blob_client = blob_service_client.get_blob_client(
                container=self.data_container,
                blob="surnames.db"
            )

            with open(self.db_path, "wb") as f:
                download_stream = blob_client.download_blob()
                f.write(download_stream.readall())

            logger.info(f"✅ Downloaded surnames.db to {self.db_path}")

        except Exception as e:
            logger.error(f"❌ Failed to download surnames.db: {e}")
            raise

    async def verify_surname(self, asr_text: str) -> dict:
        """
        Verify surname using phonetic matching.
        Returns dict with candidates, prompt type, and LLM prompt.
        """
        # Import here to avoid loading the module until needed
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..', '..'))
        from voice_agent_integration import verify_surname_for_voice_agent

        # Run synchronous verification in executor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            verify_surname_for_voice_agent,
            asr_text,
            self.db_path
        )

        return result
