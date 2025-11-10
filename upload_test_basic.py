#!/usr/bin/env python3
"""Upload test_basic_instructions.md to Azure Blob Storage"""

import os
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get connection string
connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
if not connection_string:
    print("ERROR: AZURE_STORAGE_CONNECTION_STRING not found in environment")
    exit(1)

# Upload file
blob_service_client = BlobServiceClient.from_connection_string(connection_string)
container_name = "agent-instructions"
blob_name = "test_basic_instructions.md"
file_path = "test_basic_instructions.md"

print(f"Uploading {file_path} to {container_name}/{blob_name}...")

blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

with open(file_path, "rb") as data:
    blob_client.upload_blob(data, overwrite=True)

print(f"✅ Successfully uploaded {blob_name}")
