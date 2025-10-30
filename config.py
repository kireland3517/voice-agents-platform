import os
import logging
import json
from azure.appconfiguration import AzureAppConfigurationClient
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ConfigManager:
    """Manages company-specific configurations from Azure App Configuration and Blob Storage"""
    
    def __init__(self):
        self.connection_string = os.getenv("APP_CONFIG_CONNECTION_STRING")
        if not self.connection_string:
            raise ValueError("APP_CONFIG_CONNECTION_STRING environment variable is required")
        
        self.client = AzureAppConfigurationClient.from_connection_string(self.connection_string)
        
        # Initialize Blob Storage client
        self.blob_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.instructions_container = os.getenv("BLOB_CONTAINER_NAME", "agent-instructions")
        self.recordings_container = os.getenv("RECORDINGS_CONTAINER_NAME", "call-recordings")
        self.transcripts_container = os.getenv("TRANSCRIPTS_CONTAINER_NAME", "call-transcripts")
        
        if self.blob_connection_string:
            self.blob_service_client = BlobServiceClient.from_connection_string(self.blob_connection_string)
            logger.info(f"ConfigManager initialized with Blob Storage support")
            logger.info(f"  Instructions container: {self.instructions_container}")
            logger.info(f"  Recordings container: {self.recordings_container}")
            logger.info(f"  Transcripts container: {self.transcripts_container}")
        else:
            self.blob_service_client = None
            logger.warning("AZURE_STORAGE_CONNECTION_STRING not set")
        
        logger.info("ConfigManager initialized successfully")
    
    def get_detailed_instructions(self, company_id):
        """Fetch detailed instructions from Blob Storage"""
        if not self.blob_service_client:
            logger.warning("Blob Storage not configured - skipping detailed instructions")
            return None
        
        try:
            blob_name = f"{company_id}-instructions.txt"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.instructions_container,
                blob=blob_name
            )
            
            blob_data = blob_client.download_blob()
            instructions_text = blob_data.readall().decode('utf-8')
            
            logger.info(f"Successfully loaded detailed instructions for {company_id} from Blob Storage")
            return instructions_text
            
        except Exception as e:
            logger.warning(f"Could not load detailed instructions for {company_id}: {e}")
            return None
    
    def save_call_recording(self, company_id, call_sid, audio_data, file_format="wav"):
        """Save call recording to Blob Storage"""
        if not self.blob_service_client:
            logger.error("Cannot save recording - Blob Storage not configured")
            return False
        
        try:
            blob_name = f"{company_id}/{call_sid}.{file_format}"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.recordings_container,
                blob=blob_name
            )
            
            blob_client.upload_blob(audio_data, overwrite=True)
            logger.info(f"✅ Saved recording: {blob_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save recording {call_sid}: {e}")
            return False
    
    def save_call_transcript(self, company_id, call_sid, transcript_data):
        """Save call transcript to Blob Storage"""
        if not self.blob_service_client:
            logger.error("Cannot save transcript - Blob Storage not configured")
            return False
        
        try:
            blob_name = f"{company_id}/{call_sid}.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.transcripts_container,
                blob=blob_name
            )
            
            # Convert transcript to JSON
            transcript_json = json.dumps(transcript_data, indent=2)
            blob_client.upload_blob(transcript_json.encode('utf-8'), overwrite=True)
            logger.info(f"✅ Saved transcript: {blob_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save transcript {call_sid}: {e}")
            return False
    
    def get_json_config_section(self, company_id, section_name):
        """Get a JSON configuration section for a company"""
        key = f"{company_id}/{section_name}"
        try:
            setting = self.client.get_configuration_setting(key=key)
            
            if setting is not None and setting.value:
                # Parse JSON value
                return json.loads(setting.value)
            else:
                logger.warning(f"Config section {key} not found")
                return {}
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON for {key}: {e}")
            return {}
        except Exception as e:
            logger.warning(f"Could not fetch config section {key}: {e}")
            return {}
    
    def get_company_config(self, company_id):
        """Get all configuration for a specific company from hierarchical JSON structure"""
        try:
            config = {}
            
            # Get basic-info (company-name, greeting, industry)
            basic_info = self.get_json_config_section(company_id, "basic-info")
            config.update(basic_info)  # Add top-level keys
            
            # Get voice-config
            voice_config = self.get_json_config_section(company_id, "voice-config")
            config['voice-config'] = voice_config
            
            # Get contact-info
            contact_info = self.get_json_config_section(company_id, "contact-info")
            config['contact-info'] = contact_info
            
            # Get business-rules
            business_rules = self.get_json_config_section(company_id, "business-rules")
            config['business-rules'] = business_rules

            # Get business-hours
            business_hours = self.get_json_config_section(company_id, "business-hours")
            config['business-hours'] = business_hours

            # Get audio-settings
            audio_settings = self.get_json_config_section(company_id, "audio-settings")
            
            # Apply defaults for audio settings if not present
            if not audio_settings.get('vad-threshold'):
                audio_settings['vad-threshold'] = 0.3  # Lower = more sensitive to interruptions
            if not audio_settings.get('vad-silence-duration-ms'):
                audio_settings['vad-silence-duration-ms'] = 500  # OPTIMIZED: Reduced from 800ms (research-backed)
            if not audio_settings.get('vad-prefix-padding-ms'):
                audio_settings['vad-prefix-padding-ms'] = 200  # Audio captured before speech starts
            if not audio_settings.get('temperature'):
                audio_settings['temperature'] = 0.8
            if not audio_settings.get('max-response-tokens'):
                audio_settings['max-response-tokens'] = 1500  # OPTIMIZED: Reduced from 4096 for 20% latency improvement
            
            config['audio-settings'] = audio_settings
            
            # Get detailed instructions from Blob Storage
            detailed_instructions = self.get_detailed_instructions(company_id)
            config['detailed-instructions'] = detailed_instructions
            
            company_name = config.get('company-name', 'Unknown')
            logger.info(f"Successfully loaded all config sections for {company_id}: {company_name}")
            
            return config
            
        except Exception as e:
            logger.error(f"Failed to fetch company config for {company_id}: {e}")
            return {}
    
    def get_audio_settings(self, company_id):
        """Get audio fine-tuning settings for a company"""
        audio_settings = self.get_json_config_section(company_id, "audio-settings")

        # Apply defaults if not present
        if not audio_settings.get('vad-threshold'):
            audio_settings['vad-threshold'] = 0.3  # Lower = more sensitive to interruptions
        if not audio_settings.get('vad-silence-duration-ms'):
            audio_settings['vad-silence-duration-ms'] = 500  # OPTIMIZED: Reduced from 800ms (research-backed)
        if not audio_settings.get('vad-prefix-padding-ms'):
            audio_settings['vad-prefix-padding-ms'] = 200  # Audio captured before speech starts
        if not audio_settings.get('temperature'):
            audio_settings['temperature'] = 0.8
        if not audio_settings.get('max-response-tokens'):
            audio_settings['max-response-tokens'] = 1500  # OPTIMIZED: Reduced from 4096 for 20% latency improvement

        return audio_settings
    
    def get_config_value(self, key, default=None):
        """Get a single configuration value"""
        try:
            setting = self.client.get_configuration_setting(key=key)
            if setting is not None:
                logger.debug(f"Retrieved config: {key}")
                return setting.value
            else:
                logger.warning(f"Config key {key} not found, using default: {default}")
                return default
        except Exception as e:
            logger.warning(f"Could not fetch config key {key}: {e}, using default: {default}")
            return default