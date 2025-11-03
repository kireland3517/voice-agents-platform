#!/usr/bin/env python3
"""
Upload Cedar Instructions v2 Improved to Blob Storage

This script uploads the production-ready cedar_instructions_realtime_v2_improved.md
file to Azure Blob Storage as a new blob: cedar_instructions_realtime_v2_improved.md

Usage:
    python upload_cedar_v2_improved.py
"""

import os
import logging
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def upload_instructions():
    """Upload Cedar v2 improved instructions to Blob Storage"""

    # Get connection string from environment
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        logger.error("AZURE_STORAGE_CONNECTION_STRING not set in environment")
        return False

    # Configuration
    container_name = os.getenv("BLOB_CONTAINER_NAME", "agent-instructions")
    local_file_path = "cedar_instructions_realtime_v2_improved.md"
    blob_name = "cedar_instructions_realtime_v2_improved.md"

    try:
        # Read the local file
        logger.info(f"Reading local file: {local_file_path}")
        with open(local_file_path, 'r', encoding='utf-8') as f:
            instructions_content = f.read()

        file_size = len(instructions_content)
        logger.info(f"File size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

        # Create blob service client
        logger.info(f"Connecting to Azure Blob Storage...")
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)

        # Get blob client
        blob_client = blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        # Upload the file
        logger.info(f"Uploading to blob: {container_name}/{blob_name}")
        blob_client.upload_blob(
            instructions_content.encode('utf-8'),
            overwrite=True,
            content_type='text/markdown'
        )

        logger.info("✅ Upload successful!")
        logger.info(f"   Container: {container_name}")
        logger.info(f"   Blob name: {blob_name}")
        logger.info(f"   Size: {file_size:,} bytes")

        # Verify upload by downloading first 100 characters
        logger.info("Verifying upload...")
        downloaded = blob_client.download_blob()
        content = downloaded.readall().decode('utf-8')
        logger.info(f"   First 100 chars: {content[:100]}")

        logger.info("✅ Verification successful!")

        return True

    except FileNotFoundError:
        logger.error(f"❌ File not found: {local_file_path}")
        logger.error("   Make sure cedar_instructions_realtime_v2_improved.md exists in the current directory")
        return False
    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def main():
    logger.info("=" * 80)
    logger.info("Cedar Instructions v2 Improved - Upload to Blob Storage")
    logger.info("=" * 80)

    success = upload_instructions()

    if success:
        logger.info("\n" + "=" * 80)
        logger.info("✅ UPLOAD COMPLETE")
        logger.info("=" * 80)
        logger.info("\nNext steps:")
        logger.info("1. Update config.py line 56 to use new blob name:")
        logger.info("   blob_name = 'cedar_instructions_realtime_v2_improved.md'")
        logger.info("2. OR keep existing name and overwrite cedar_instructions.md:")
        logger.info("   Re-run with blob_name = 'cedar_instructions.md'")
        logger.info("=" * 80)
    else:
        logger.error("\n" + "=" * 80)
        logger.error("❌ UPLOAD FAILED")
        logger.error("=" * 80)

if __name__ == "__main__":
    main()
