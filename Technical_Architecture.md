# Multi-Tenant Voice Agent Platform - Technical Architecture

**Version:** 2.0
**Date:** October 30, 2025
**Status:** Production Ready (Voice Live API)

---

## System Overview

Real-time, human-sounding AI voice agent platform supporting multiple companies with isolated configurations. Enables natural voice conversations via SignalWire phone integration and Azure Voice Live API with Azure TTS voices for consistent prosody and SSML support.

---

## Configuration Layers

### 1. Azure App Configuration
**Purpose:** Per-company business configuration that changes without code deployment

**Structure:** `{company-id}/{section-name}` with JSON values

**Content:**
- `basic-info` - Company identity (name, greeting, industry)
- `voice-config` - Voice preferences (Azure TTS voice selection)
- `business-hours` - Timezone, days, open/close times (configurable per company)
- `contact-info` - Phone, email for agent reference
- `audio-settings` - VAD threshold (0.3), silence duration (800ms), prefix padding (200ms), temperature (0.8), max tokens (4096)
- `business-rules` - Callback timeframes, transfer policies
- Feature flags - Enable/disable recordings, transcripts

**Exclusions:**
- Large text content (use Blob Storage)
- API keys or secrets (use Environment Variables)
- Technical constants (use code)
- Call flow logic (use code)

### 2. Azure Blob Storage

**Container: agent-instructions/**
- Full MODEL INSTRUCTIONS documents per company
- Format: `{company-id}-instructions.txt`
- Content: Complete system prompt, personality, policies, scenarios

**Container: call-recordings/**
- Audio files from completed calls
- Format: `{company-id}/{call-sid}-caller.wav` and `{call-sid}-ai.wav`
- Retention: Per compliance requirements

**Container: call-transcripts/**
- Timestamped conversation logs
- Format: `{company-id}/{call-sid}.json`
- Content: Turn-by-turn with timestamps

### 3. Environment Variables (Container Apps)
**Purpose:** Secrets, endpoints, and deployment-specific settings

**Content:**
- Azure AI endpoint and API key (Voice Live API)
- Azure AI model deployment name (gpt-4o-mini-realtime-preview)
- App Configuration connection string
- Blob Storage connection string
- Container names (instructions, recordings, transcripts)
- Feature toggles (SAVE_RECORDINGS, SAVE_TRANSCRIPTS)
- Environment identifier (production, staging)
- Log level

**Exclusions:**
- Business logic
- Company-specific data
- Audio format specifications

---

## Code Structure

### Infrastructure Layer

**app.py**
- FastAPI application setup
- WebSocket route definitions
- Health check endpoints
- Configuration caching (LRU cache wrapper)
- Environment validation at startup
- Logging configuration
- Server initialization

### Service Layer

**config.py (ConfigManager)**
- Azure App Configuration client
- Blob Storage client initialization
- Fetch hierarchical JSON sections (basic-info, voice-config, audio-settings, business-hours, contact-info, business-rules)
- Fetch detailed instructions from Blob
- Save recordings and transcripts
- Config validation and defaults
- Apply configurable VAD settings

**zipcode_service.py (ZipcodeService)**
- ZIP code lookup from us-zipcodes.csv
- City and state resolution
- Async HTTP client for geocoding

**surname_verifier.py**
- Phonetic surname matching
- LLM prompt generation for spelling confirmation
- Candidate surname suggestions

### Handler Layer

**app.py - Main Application**
- voice_bridge() - WebSocket handler for SignalWire connections
- send_signalwire_audio_to_voicelive() - Audio forwarding loop
- handle_voicelive_event() - Voice Live API event processing
- create_voicelive_connection() - Voice Live SDK initialization with Azure TTS voice
- Call session lifecycle (start, active, end)
- Audio streaming in both directions (PCM16, 24kHz)
- Event routing and handling
- Greeting trigger logic with 1.5s delay
- Call context injection (date, time, business hours, caller ID)
- Business hours detection with overnight support
- Recording buffer management

### Model Layer

**CallSession class (app.py)**
- Session state tracking
- Recording buffers (caller and AI audio as PCM16)
- Transcript accumulation
- Finalize and save_to_storage methods
- WAV file creation from PCM buffers

### Supporting Modules

**constants.py**
- Audio format specifications (pcm16, 24000Hz, 16-bit, mono)
- API version strings
- Event type definitions
- Timeout values
- Buffer size limits
- Default VAD settings

**utils/phone.py**
- Format US phone numbers for display
- Validate phone number format
- Parse caller ID strings

**utils/time.py**
- Check if current time is within business hours config
- Timezone conversions
- Format timestamps for display

---

## External Systems

### SignalWire Configuration
**Purpose:** Route incoming calls to correct company agent

**cXML per phone number:**
- WebSocket URL with company-id path parameter
- Codec specification (L16@24000h)
- Bidirectional stream setup

**Content:**
- Call routing (which phone number → which company-id)
- Audio codec settings
- Stream connection parameters

**Exclusions:**
- Business logic
- Agent instructions
- Company branding

### Azure Voice Live API
**SDK:** azure-ai-voicelive
**Model:** gpt-4o-mini-realtime-preview
**Voice:** en-US-FableTurboMultilingualNeural (Azure TTS)
**Audio:** PCM16, 24kHz, mono, bidirectional streaming
**Features:**
- Server-side VAD (configurable per company)
- Azure TTS voices with SSML support
- Consistent prosody throughout conversations
- Natural conversation flow
- Interruption handling

---

## Data Flow

### Call Initiation
1. SignalWire receives phone call
2. SignalWire connects to WebSocket `/voice/{company-id}`
3. Platform fetches company config from App Configuration (with 5-minute cache)
4. Platform fetches detailed instructions from Blob Storage
5. Platform establishes Azure Voice Live API connection
6. Platform configures session with Azure TTS voice (en-US-FableTurboMultilingualNeural)
7. Platform applies configurable VAD settings from audio-settings config
8. Platform injects call context (date, time, business hours, caller ID)
9. Platform waits 1.5s for audio stream establishment
10. Platform triggers initial greeting via response.create()

### Active Call
1. SignalWire streams caller audio (PCM16, 24kHz) to platform
2. Platform forwards audio to Voice Live API via input_audio_buffer.append()
3. Voice Live API processes with server-side VAD
4. Voice Live API generates response with Azure TTS voice
5. Platform receives audio via ServerEventType.RESPONSE_AUDIO_DELTA events
6. Platform forwards AI audio to SignalWire
7. Platform buffers both audio streams for recording
8. Platform tracks transcript in real-time (caller and AI)
9. Voice Live API's VAD handles turn detection and interruptions

### Call Termination
1. SignalWire sends stop event
2. Platform finalizes call session
3. Platform creates WAV files from PCM audio buffers
4. Platform uploads recordings to Blob Storage (caller.wav and ai.wav)
5. Platform uploads transcript to Blob Storage (JSON with timestamps)
6. Voice Live API connection closes automatically
7. Platform cleans up session state

---

## Identified Gaps

### Critical for Demo (5 Successful Calls)

#### 1. Error Handling Strategy
**Status:** Missing  
**Impact:** High - Single failure crashes entire call

**Required:**
- Azure OpenAI disconnect mid-call handling
- Blob Storage upload failure recovery
- App Configuration unreachable fallback
- Retry logic for transient failures
- Graceful call termination on fatal errors
- User-friendly error messages to caller

**Implementation Needed:**
- Try-catch blocks around all Azure service calls
- Exponential backoff retry for network errors
- Circuit breaker pattern for failing dependencies
- Fallback greeting if config load fails
- Log error details without exposing to caller

#### 2. Config Validation
**Status:** Partial - Basic key checks only  
**Impact:** High - Invalid config causes runtime errors

**Required:**
- Schema validation for App Configuration JSON
- Required vs optional fields enforcement
- Type checking (strings, numbers, arrays)
- Range validation (VAD threshold 0.0-1.0)
- Validate before accepting call
- Clear error messages if config incomplete

**Implementation Needed:**
- Pydantic models for config schemas
- Validation at config load time
- Startup validation for all companies
- Config health check endpoint

#### 3. Graceful Degradation
**Status:** Missing  
**Impact:** Medium - System fails when optional data missing

**Required:**
- Fallback if detailed instructions blob missing
- Default values if audio-settings missing
- Sensible behavior if business-hours config absent
- Generic greeting if company greeting missing

**Implementation Needed:**
- Default instruction template
- Default audio settings dictionary
- Always-open fallback for business hours
- Generic "thank you for calling" greeting

#### 4. Local Development Setup
**Status:** Incomplete  
**Impact:** Medium - Slows development and testing

**Required:**
- Run and test locally without Azure
- Mock Azure services for development
- Sample configuration data
- Local WebSocket testing approach
- Hot reload for code changes

**Implementation Needed:**
- Local .env with mock endpoints
- In-memory config store for dev mode
- Local file storage instead of Blob
- ngrok or similar for SignalWire testing
- Development mode flag

---

### Important for Production (Post-Demo)

#### 5. Monitoring & Observability
**Status:** Basic logging only  
**Impact:** High - Cannot diagnose issues in production

**Required:**
- Application Insights integration
- Call success/failure metrics
- Latency tracking (SignalWire, Azure, end-to-end)
- Error rate alerting
- Real-time dashboard
- Performance counters

**Implementation Needed:**
- Azure Monitor integration
- Custom metrics and events
- Distributed tracing
- Alert rules and action groups
- Dashboard templates

#### 6. Call Metadata Storage
**Status:** Missing  
**Impact:** Medium - Cannot analyze call patterns or outcomes

**Required:**
- Database for call outcomes
- Track transfer attempts, completion status
- Link recordings to call metadata
- Query call history per company
- Duration, timestamp, caller ID storage

**Implementation Needed:**
- Azure Table Storage or Cosmos DB
- Schema for call records
- APIs for querying call history
- Retention policies

#### 7. Security
**Status:** Basic - HTTPS only  
**Impact:** High - Vulnerable to attacks and data exposure

**Required:**
- SignalWire webhook signature verification
- API endpoint authentication
- PII redaction in transcripts
- Encryption at rest for recordings
- Role-based access control
- Audit logging

**Implementation Needed:**
- JWT authentication for admin APIs
- Managed Identity for Azure services
- PII detection and masking
- Azure Key Vault for secrets
- Customer-managed encryption keys

#### 8. Rate Limiting
**Status:** Missing  
**Impact:** High - Runaway costs possible

**Required:**
- Azure OpenAI token limits
- Concurrent call limits per company
- Cost controls and budgets
- Throttling for abusive callers

**Implementation Needed:**
- Rate limiting middleware
- Per-company quotas
- Token usage tracking
- Automatic circuit breaking at thresholds

#### 9. Testing Framework
**Status:** Manual testing only  
**Impact:** Medium - Cannot validate changes confidently

**Required:**
- Unit tests for utils and services
- Integration tests for call flow
- Load testing strategy
- Regression test suite
- Automated test execution

**Implementation Needed:**
- pytest framework setup
- Mock WebSocket connections
- Test fixtures for config
- CI pipeline integration
- Load testing with Locust or k6

#### 10. Deployment Pipeline
**Status:** Manual deployment  
**Impact:** Medium - Slow releases, human error risk

**Required:**
- CI/CD automation
- Health checks before live traffic
- Rollback procedures
- Blue/green deployment
- Automated testing gates

**Implementation Needed:**
- GitHub Actions or Azure DevOps pipelines
- Container build automation
- Deployment validation checks
- Automated rollback triggers

#### 11. Documentation
**Status:** Partial - Code comments only  
**Impact:** Medium - Onboarding and troubleshooting difficult

**Required:**
- Runbook for adding new companies
- Troubleshooting guide
- Architecture diagrams
- API documentation
- Operations manual

**Implementation Needed:**
- Step-by-step onboarding guide
- Common issues and solutions
- System architecture diagrams
- OpenAPI/Swagger specs
- On-call playbook

---

## Decision Rules

**Configuration Changes (No Deployment):**
- Different per company → Azure App Configuration
- Large text content → Blob Storage

**Code Changes (Deployment Required):**
- Technical constant → constants.py
- Business logic → services/
- Call flow → handlers/
- Reusable helper → utils/

**Secrets:**
- Always → Environment Variables

---

## Success Criteria

### Demo Phase (Immediate)
- 5 consecutive successful calls without crashes
- Accurate business hours detection and response
- Natural conversation flow with greeting protection
- Barge-in works after greeting completes
- All 5 recordings and transcripts saved correctly

### Production Phase (Future)
- 99.9% uptime over 30 days
- Average latency <500ms
- Error rate <0.1%
- Zero security incidents
- Cost per call <$5
- Support 100+ concurrent calls

---

## Next Steps

1. Implement error handling strategy (#1)
2. Add config validation (#2)
3. Build graceful degradation (#3)
4. Setup local development environment (#4)
5. Execute 5 test calls
6. Address production gaps based on learnings
