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
            # UPDATED: Use cedar_instructions.md (inline SSML not supported by Voice Live API)
            if company_id == "senior-life":
                blob_name = "cedar_instructions.md"
            else:
                # Fallback pattern for other companies
                blob_name = f"{company_id}-instructions.txt"
                
            blob_client = self.blob_service_client.get_blob_client(
                container=self.instructions_container,
                blob=blob_name
            )
            
            blob_data = blob_client.download_blob()
            instructions_text = blob_data.readall().decode('utf-8')
            
            logger.info(f"Successfully loaded detailed instructions for {company_id} from Blob Storage ({blob_name})")
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
            
            # =========================================================================
            # RESEARCH-BACKED OPTIMAL SETTINGS (Human Voice Agent Guide)
            # =========================================================================

            # VAD Settings - Research shows these values optimal for voice agents
            # Guide Section: Turn-Taking and Interruption Handling
            if not audio_settings.get('vad-threshold'):
                audio_settings['vad-threshold'] = 0.3  # Guide: 0.3 for insurance (sensitive)
            if not audio_settings.get('vad-silence-duration-ms'):
                audio_settings['vad-silence-duration-ms'] = 500  # Guide: 500-600ms sweet spot
            if not audio_settings.get('vad-prefix-padding-ms'):
                audio_settings['vad-prefix-padding-ms'] = 300  # Guide: 300ms prevents cutoff
            if not audio_settings.get('vad-end-utterance-timeout-ms'):
                audio_settings['vad-end-utterance-timeout-ms'] = 2000  # Guide: 2s timeout (was 1000)

            # Adaptive VAD Settings for Different Customer Types
            # Guide: Elderly customers need longer pauses, emotional contexts need patience
            if not audio_settings.get('vad-silence-duration-elderly-ms'):
                audio_settings['vad-silence-duration-elderly-ms'] = 700  # Guide: 600-700ms for elderly
            if not audio_settings.get('vad-silence-duration-claims-ms'):
                audio_settings['vad-silence-duration-claims-ms'] = 700  # Guide: 700ms for emotional contexts
            if not audio_settings.get('vad-silence-duration-noisy-ms'):
                audio_settings['vad-silence-duration-noisy-ms'] = 400  # Guide: 400ms in noisy environments
            if not audio_settings.get('vad-threshold-noisy'):
                audio_settings['vad-threshold-noisy'] = 0.6  # Guide: Higher threshold for noise
                
            # LLM Settings - Optimized for latency
            if not audio_settings.get('temperature'):
                audio_settings['temperature'] = 0.8  # Default for conversational

            # Force the optimal setting for gpt-realtime-mini
            # The 4096 value in AppConfig is legacy and causes latency
            # Guide: 150-200 tokens optimal for conversational responses
            audio_settings['max-response-tokens'] = 200  # Guide: Keep responses short for natural flow
            
            # Transcription Settings - Better accuracy
            if not audio_settings.get('transcription-temperature'):
                audio_settings['transcription-temperature'] = 0.0  # Deterministic for consistency
            if not audio_settings.get('transcription-prompt'):
                # Default domain terms for insurance industry (comma-separated string)
                audio_settings['transcription-prompt'] = (
                    "Cedar, Senior Life Insurance, Medicare, Medicaid, "
                    "copay, deductible, premium, beneficiary"
                )

            # Audio Processing Settings
            if not audio_settings.get('audio-sample-rate'):
                audio_settings['audio-sample-rate'] = 24000  # Required for Voice Live API
                
            # Advanced Features - All enabled by default per research
            if not audio_settings.get('enable-semantic-vad'):
                audio_settings['enable-semantic-vad'] = True  # 40-60% fewer false turn endings
            if not audio_settings.get('enable-noise-suppression'):
                audio_settings['enable-noise-suppression'] = True  # 60% noise reduction
            if not audio_settings.get('enable-echo-cancellation'):
                audio_settings['enable-echo-cancellation'] = True  # Prevents feedback loops
            if not audio_settings.get('enable-audio-transcription'):
                audio_settings['enable-audio-transcription'] = True  # Whisper for quality
            if 'remove-filler-words' not in audio_settings:
                audio_settings['remove-filler-words'] = False  # DO NOT remove fillers - respect natural speech cadence
                logger.info("Setting 'remove-filler-words' to FALSE for natural VAD.")
            
            # Connection & Monitoring Settings
            if not audio_settings.get('heartbeat-interval-seconds'):
                audio_settings['heartbeat-interval-seconds'] = 30  # Keep-alive interval
            if not audio_settings.get('connection-retry-attempts'):
                audio_settings['connection-retry-attempts'] = 3  # Resilience
            if not audio_settings.get('token-warning-threshold'):
                audio_settings['token-warning-threshold'] = 100000  # ~78% of 128k limit
            if not audio_settings.get('max-turns-before-text-conversion'):
                audio_settings['max-turns-before-text-conversion'] = 10  # Save tokens
            
            # =========================================================================
            # VOICE NATURALNESS SETTINGS (Guide: Voice Synthesis for Maximum Naturalness)
            # =========================================================================

            # Voice HD Neural Settings - Applied at voice config level, not per-response
            # Guide: HD voices with temperature create foundation for natural sound
            if not audio_settings.get('voice-temperature'):
                audio_settings['voice-temperature'] = 0.8  # Guide: 0.7-0.8 for natural prosody
            if not audio_settings.get('voice-rate'):
                audio_settings['voice-rate'] = "1.0"  # Guide: 0.9-1.05 for professional (100% normal)
            if not audio_settings.get('voice-pitch'):
                audio_settings['voice-pitch'] = "+0%"  # Guide: -1 to +1 semitone for warmth
            if not audio_settings.get('voice-volume'):
                audio_settings['voice-volume'] = "+10%"  # Clarity for phone audio
            if not audio_settings.get('voice-style'):
                audio_settings['voice-style'] = "customerservice"  # Guide: Professional warmth
            if not audio_settings.get('voice-style-degree'):
                audio_settings['voice-style-degree'] = 1.3  # Guide: 1.2-1.4 for insurance contexts
            if not audio_settings.get('ssml-style-degree'):
                audio_settings['ssml-style-degree'] = 1.2  # Research: 1.2-1.5 natural

            # =========================================================================
            # LATENCY OPTIMIZATION (Guide: Target 600-800ms voice-to-voice)
            # =========================================================================

            # Component Latency Targets (Guide Section: Latency Optimization)
            if not audio_settings.get('latency-target-total-ms'):
                audio_settings['latency-target-total-ms'] = 800  # Guide: 600-800ms total
            if not audio_settings.get('latency-target-stt-ms'):
                audio_settings['latency-target-stt-ms'] = 250  # Guide: 200-300ms for STT
            if not audio_settings.get('latency-target-llm-ms'):
                audio_settings['latency-target-llm-ms'] = 250  # Guide: 200-300ms for LLM
            if not audio_settings.get('latency-target-tts-ms'):
                audio_settings['latency-target-tts-ms'] = 150  # Guide: 100-150ms for TTS
            if not audio_settings.get('latency-target-network-ms'):
                audio_settings['latency-target-network-ms'] = 100  # Guide: ~100ms for network

            # Latency Warning Thresholds (Guide: Perceived Responsiveness)
            if not audio_settings.get('latency-warning-slow-ms'):
                audio_settings['latency-warning-slow-ms'] = 1000  # Guide: >1000ms = noticeable delay
            if not audio_settings.get('latency-warning-very-slow-ms'):
                audio_settings['latency-warning-very-slow-ms'] = 1500  # Guide: >1500ms = frustrating
            if not audio_settings.get('latency-warning-instant-ms'):
                audio_settings['latency-warning-instant-ms'] = 100  # Guide: <100ms = sounds robotic

            config['audio-settings'] = audio_settings
            
            # Get detailed instructions from Blob Storage
            detailed_instructions = self.get_detailed_instructions(company_id)
            config['detailed-instructions'] = detailed_instructions
            
            company_name = config.get('company-name', 'Unknown')
            logger.info(f"Successfully loaded all config sections for {company_id}: {company_name}")
            
            # Log optimization status
            logger.info(f"""
            ✅ OPTIMIZATIONS ACTIVE for {company_name}:
               VAD: threshold={audio_settings['vad-threshold']}, silence={audio_settings['vad-silence-duration-ms']}ms
               Tokens: max={audio_settings['max-response-tokens']} (optimized for speed)
               Semantic VAD: {audio_settings['enable-semantic-vad']}
               Noise Suppression: {audio_settings['enable-noise-suppression']}
            """)
            
            return config
            
        except Exception as e:
            logger.error(f"Failed to fetch company config for {company_id}: {e}")
            return {}
    
    def get_audio_settings(self, company_id):
        """Get audio fine-tuning settings for a company"""
        audio_settings = self.get_json_config_section(company_id, "audio-settings")

        # Apply the same research-backed defaults as above
        if not audio_settings.get('vad-threshold'):
            audio_settings['vad-threshold'] = 0.5  # Research: 0.5 balanced
        if not audio_settings.get('vad-silence-duration-ms'):
            audio_settings['vad-silence-duration-ms'] = 500  # Research: 500ms sweet spot
        if not audio_settings.get('vad-prefix-padding-ms'):
            audio_settings['vad-prefix-padding-ms'] = 300  # Research: 300ms optimal
        if not audio_settings.get('vad-end-utterance-timeout-ms'):
            audio_settings['vad-end-utterance-timeout-ms'] = 1000  # Prevents hanging
        if not audio_settings.get('temperature'):
            audio_settings['temperature'] = 0.8

        # Force the optimal setting for gpt-realtime-mini
        audio_settings['max-response-tokens'] = 1500  # 20% latency improvement
        if not audio_settings.get('transcription-temperature'):
            audio_settings['transcription-temperature'] = 0.0

        # Ensure all advanced features enabled
        if not audio_settings.get('enable-semantic-vad'):
            audio_settings['enable-semantic-vad'] = True
        if not audio_settings.get('enable-noise-suppression'):
            audio_settings['enable-noise-suppression'] = True
        if not audio_settings.get('enable-echo-cancellation'):
            audio_settings['enable-echo-cancellation'] = True
        if not audio_settings.get('enable-audio-transcription'):
            audio_settings['enable-audio-transcription'] = True
        if 'remove-filler-words' not in audio_settings:
            audio_settings['remove-filler-words'] = False  # DO NOT remove fillers - respect natural speech cadence

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
