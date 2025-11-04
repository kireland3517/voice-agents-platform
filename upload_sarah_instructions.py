#!/usr/bin/env python3
"""
Upload Sarah instructions to Azure Blob Storage
"""
import os
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

# Get connection string from environment
connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
if not connection_string:
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")

# Configuration
container_name = "agent-instructions"
blob_name = "sarah_instructions_senior_life.md"
local_file_path = "sarah_instructions_senior_life.md"

# Create blob service client
blob_service_client = BlobServiceClient.from_connection_string(connection_string)

# Get blob client
blob_client = blob_service_client.get_blob_client(
    container=container_name,
    blob=blob_name
)

# Upload file
print(f"Uploading {local_file_path} to blob storage...")
with open(local_file_path, "rb") as data:
    blob_client.upload_blob(data, overwrite=True)

print(f"✅ Successfully uploaded {blob_name} to {container_name} container")
