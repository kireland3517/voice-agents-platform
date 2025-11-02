# Azure Voice Live API - Architecture Diagrams

This document contains visual Mermaid diagrams illustrating the system architecture and data flows for the Azure Voice Live API integration.

**Last Updated:** November 1, 2025
**Version:** 20.0 - Production with Function Calling

**Recent Updates:**
- ✅ Added Function Calling architecture (v20.0)
- ✅ Added Raw WebSocket bypass for function outputs
- ✅ Added SessionMonitor and production optimizations
- ✅ Updated audio chunking to 100ms optimal chunks
- ✅ Removed unsupported transcription parameters (temperature, phrase_list)
- ✅ Added connection retry and heartbeat logic

---

## 1. Overall System Architecture

```mermaid
graph TB
    subgraph "Telephony Layer"
        Phone[📞 Customer Phone]
        PSTN[PSTN Network]
    end

    subgraph "Azure Communication Services"
        ACS[ACS Resource]
        PhoneNum[Phone Number<br/>+1-833-XXX-XXXX]
        CallAuto[Call Automation API]
        MediaStream[Media Streaming<br/>PCM 24kHz]
    end

    subgraph "Application Layer - Container Apps"
        Server[server.py<br/>Quart Web Server]
        EventHandler[ACS Event Handler<br/>Incoming Calls & Callbacks]
        MediaHandler[ACS Media Handler<br/>Audio Streaming]
    end

    subgraph "AI/Speech Layer"
        VoiceLive[Azure AI Foundry<br/>Voice Live API]
        STT[Speech-to-Text<br/>Whisper]
        LLM[LLM Processing<br/>gpt-4o-mini-realtime-preview]
        TTS[Text-to-Speech<br/>Azure Neural Voice]
    end

    subgraph "Business Logic Services"
        ConfigMgr[Config Manager]
        SurnameSvc[Surname Service<br/>162K Database]
        ZipSvc[ZIP Code Service<br/>808KB CSV]
        BusinessHrs[Business Hours<br/>Logic]
    end

    subgraph "Azure Storage & Config"
        AppConfig[Azure App Configuration<br/>Company Configs]
        BlobInstr[Blob: agent-instructions<br/>System Prompts]
        BlobData[Blob: agent-data<br/>surnames.db]
        BlobRec[Blob: call-recordings<br/>Audio WAV Files]
        BlobTrans[Blob: call-transcripts<br/>JSON Transcripts]
    end

    Phone --> PSTN
    PSTN --> PhoneNum
    PhoneNum --> ACS
    ACS --> CallAuto
    CallAuto --> EventHandler
    EventHandler --> Server
    Server --> MediaHandler

    MediaHandler <-->|WebSocket<br/>Audio Streaming| MediaStream
    MediaStream <-->|Bidirectional<br/>PCM Audio| VoiceLive

    VoiceLive --> STT
    STT --> LLM
    LLM --> TTS
    TTS --> VoiceLive

    MediaHandler --> SurnameSvc
    MediaHandler --> ZipSvc
    MediaHandler --> BusinessHrs
    MediaHandler --> ConfigMgr

    ConfigMgr --> AppConfig
    ConfigMgr --> BlobInstr
    SurnameSvc --> BlobData
    MediaHandler --> BlobRec
    MediaHandler --> BlobTrans

    style Phone fill:#e1f5ff
    style ACS fill:#0078d4,color:#fff
    style Server fill:#52b788
    style VoiceLive fill:#ff6b6b,color:#fff
    style AppConfig fill:#ffd93d
    style BlobData fill:#ffd93d
```

---

## 2. Call Initiation Sequence

```mermaid
sequenceDiagram
    participant Customer
    participant PSTN
    participant ACS
    participant EventGrid
    participant App as Application<br/>(server.py)
    participant VoiceLive as Voice Live API
    participant AppConfig as Azure App Config
    participant Blob as Azure Blob Storage

    Customer->>PSTN: Dials phone number
    PSTN->>ACS: Routes call to ACS number

    rect rgb(200, 230, 255)
        Note over ACS,EventGrid: Event Grid Integration
        ACS->>EventGrid: IncomingCall event<br/>(includes caller ID)
        EventGrid->>App: POST /acs/incomingcall<br/>(caller phone number)
        Note right of App: Extract caller ID:<br/>+18335551234
    end

    rect rgb(255, 230, 200)
        Note over App,Blob: Configuration Loading
        App->>AppConfig: Get company config<br/>(senior-life/*)
        AppConfig-->>App: Voice settings (temp >= 0.6),<br/>business rules, VAD (0.5/500/300)
        Note right of App: Validate temperature:<br/>Auto-correct if < 0.6
        App->>Blob: Get detailed instructions<br/>(senior-life-instructions.txt)
        Blob-->>App: System prompt content
        Note right of App: ONLY source for<br/>detailed instructions
        App->>Blob: Download surnames.db<br/>(if not cached)
        Blob-->>App: 800KB database file
    end

    rect rgb(200, 255, 200)
        Note over App,ACS: Answer Call with Media Streaming
        App->>ACS: Answer call<br/>+ MediaStreamingOptions<br/>(WebSocket URL + caller ID param, PCM24K)
        Note right of App: Pass caller ID via<br/>query parameter
        ACS-->>App: CallConnected event<br/>+ Connection ID
    end

    rect rgb(255, 200, 255)
        Note over App,VoiceLive: Establish Voice Live Connection
        App->>VoiceLive: WebSocket connect<br/>(wss://foundry.services.ai.azure.com)
        VoiceLive-->>App: Session created
        App->>VoiceLive: session.update<br/>(instructions + caller ID context,<br/>voice config, VAD 0.5/500/300, temp >= 0.6)
        Note right of App: Inject caller ID into<br/>system instructions
        App->>VoiceLive: response.create<br/>(trigger greeting with text+audio)
        VoiceLive-->>App: Audio stream (greeting)<br/>24kHz PCM16
    end

    App->>ACS: Forward AI audio
    ACS->>PSTN: Stream audio
    PSTN->>Customer: Customer hears AI greeting

    Note over Customer,VoiceLive: Call is now active - bidirectional audio streaming
```

---

## 3. Active Call - Audio Streaming Flow

```mermaid
sequenceDiagram
    participant Customer
    participant ACS
    participant MediaHandler as Media Handler<br/>(acs_media_handler.py)
    participant VoiceLive as Voice Live API
    participant Services as Business Services<br/>(Surname, ZIP, etc.)

    rect rgb(230, 240, 255)
        Note over Customer,VoiceLive: Customer Speaking → AI Processing
        Customer->>ACS: Speaks into phone
        ACS->>MediaHandler: WebSocket: AudioData<br/>(PCM 24kHz base64)
        MediaHandler->>VoiceLive: input_audio_buffer.append

        VoiceLive-->>MediaHandler: input_audio_buffer.speech_started
        Note over MediaHandler: Trigger stop_audio()<br/>(barge-in detection)
        MediaHandler->>VoiceLive: response.cancel

        VoiceLive-->>MediaHandler: input_audio_buffer.speech_stopped
        VoiceLive-->>MediaHandler: conversation.item.input_audio_transcription.completed<br/>"My last name is Smith"

        Note over MediaHandler,Services: Check if surname verification needed
        MediaHandler->>Services: verify_surname("Smith")
        Services-->>MediaHandler: Perfect match: S-M-I-T-H
    end

    rect rgb(255, 240, 230)
        Note over MediaHandler,VoiceLive: AI Processing → Customer Hearing
        MediaHandler->>VoiceLive: conversation.item.create<br/>(inject surname verification prompt)
        MediaHandler->>VoiceLive: response.create

        VoiceLive-->>MediaHandler: response.audio_transcript.delta<br/>(partial text chunks)
        VoiceLive-->>MediaHandler: response.audio.delta<br/>(audio chunks in base64)

        MediaHandler->>ACS: Forward audio chunks<br/>(PCM 24kHz)
        ACS->>Customer: Streams audio to phone

        VoiceLive-->>MediaHandler: response.audio_transcript.done<br/>"Thank you. Is that spelled S-M-I-T-H?"
        Note over MediaHandler: Log complete transcript
    end

    loop Continuous Conversation
        Customer->>ACS: Continues speaking...
        Note over ACS,VoiceLive: Repeat cycle
    end
```

---

## 4. Surname Verification Integration

```mermaid
flowchart TD
    Start([AI asks for last name]) --> Listen[Media Handler listens<br/>for transcription]

    Listen --> Transcribe[Voice Live API:<br/>input_audio_transcription.completed<br/>transcript = 'Smith']

    Transcribe --> CheckFlag{Surname verification<br/>enabled?}
    CheckFlag -->|No| Continue[Continue conversation]
    CheckFlag -->|Yes| CallService[Call SurnameService.verify_surname]

    CallService --> LoadDB[Load surnames.db<br/>from blob if needed]
    LoadDB --> Phonetic[Generate phonetic keys<br/>Double Metaphone]

    Phonetic --> QueryDB[(Query SQLite database<br/>162K surnames)]

    QueryDB --> Count{How many<br/>matches?}

    Count -->|0 matches| NoMatch[Generate prompt:<br/>'Please spell your last name']
    Count -->|1 exact match| PerfectMatch[Generate prompt:<br/>'Is that spelled S-M-I-T-H?']
    Count -->|1 phonetic match| PhoneticMatch[Generate prompt:<br/>'Is that spelled F-R-A-N-K-O-W-I-T-Z?']
    Count -->|Multiple matches| MultiMatch[Generate prompt:<br/>'Is that Smith, Smyth, or Schmidt?']

    NoMatch --> InjectPrompt[Inject system prompt<br/>into Voice Live conversation]
    PerfectMatch --> InjectPrompt
    PhoneticMatch --> InjectPrompt
    MultiMatch --> InjectPrompt

    InjectPrompt --> TriggerResponse[Send response.create<br/>to Voice Live API]
    TriggerResponse --> AIResponds[AI speaks verification<br/>to customer]

    AIResponds --> End([Continue information collection])
    Continue --> End

    style Start fill:#e1f5ff
    style QueryDB fill:#ffd93d
    style NoMatch fill:#ff6b6b,color:#fff
    style PerfectMatch fill:#52b788,color:#fff
    style PhoneticMatch fill:#ffa94d
    style MultiMatch fill:#ffa94d
    style AIResponds fill:#b197fc,color:#fff
```

---

## 5. ZIP Code Lookup Flow

```mermaid
flowchart TD
    Start([AI asks for ZIP code]) --> Listen[Media Handler listens<br/>for transcription]

    Listen --> Transcribe[Voice Live API:<br/>input_audio_transcription.completed<br/>transcript = 'My ZIP is 12345']

    Transcribe --> Extract[Extract ZIP code<br/>using regex: \b\d5\b]

    Extract --> Found{ZIP code<br/>found in text?}
    Found -->|No| Continue[Continue conversation]
    Found -->|Yes| CallService[Call ZipcodeService.lookup]

    CallService --> LoadCSV[Load us-zipcodes.csv<br/>808KB, 40K+ entries]
    LoadCSV --> Search[Search for ZIP code]

    Search --> Match{ZIP found<br/>in database?}

    Match -->|No| NotFound[Continue without<br/>auto-confirmation]
    Match -->|Yes| GetCityState[Extract city and state<br/>e.g., 'Albany, New York']

    GetCityState --> InjectPrompt[Inject system prompt:<br/>'ZIP 12345 corresponds to Albany, New York.<br/>Confirm this with customer.']

    InjectPrompt --> TriggerResponse[Send response.create<br/>to Voice Live API]
    TriggerResponse --> AIConfirm[AI speaks:<br/>'So that's Albany, New York, correct?']

    AIConfirm --> End([Continue information collection])
    NotFound --> End
    Continue --> End

    style Start fill:#e1f5ff
    style LoadCSV fill:#ffd93d
    style GetCityState fill:#52b788,color:#fff
    style AIConfirm fill:#b197fc,color:#fff
```

---

## 6. Business Hours Logic Flow

```mermaid
flowchart TD
    Start([Session configuration<br/>loading]) --> GetConfig[Get business-hours config<br/>from Azure App Configuration]

    GetConfig --> ParseConfig[Parse configuration:<br/>timezone, days, open/close times]

    ParseConfig --> GetTime[Get current time<br/>in business timezone<br/>using pytz]

    GetTime --> ParseTimes[Parse open/close times<br/>Convert to minutes]

    ParseTimes --> CheckOvernight{close time <<br/>open time?}

    CheckOvernight -->|No: Standard Hours| StandardCheck[Check:<br/>Is business day + within hours?]

    CheckOvernight -->|Yes: Overnight Hours| OvernightCheck[Check:<br/>After open OR before close<br/>from yesterday?]

    StandardCheck --> IsOpen{Currently in<br/>business hours?}
    OvernightCheck --> IsOpen

    IsOpen -->|Yes - OPEN| OpenPrompt[Inject prompt:<br/>Status: OPEN<br/>Can transfer to agent]
    IsOpen -->|No - CLOSED| ClosedPrompt[Inject prompt:<br/>Status: CLOSED<br/>Offer callback only]

    OpenPrompt --> AddToSession[Add to Voice Live<br/>session instructions]
    ClosedPrompt --> AddToSession

    AddToSession --> End([AI uses this context<br/>in conversation])

    style Start fill:#e1f5ff
    style CheckOvernight fill:#ffa94d
    style OpenPrompt fill:#52b788,color:#fff
    style ClosedPrompt fill:#ff6b6b,color:#fff
    style AddToSession fill:#b197fc,color:#fff

    Note1[Example Overnight:<br/>Mon 8am - Tue 2am<br/><br/>Mon 10pm = OPEN<br/>Tue 1am = OPEN<br/>Tue 3am = CLOSED]

    style Note1 fill:#fff4e6
    Note1 -.->|Explains| OvernightCheck
```

---

## 7. Call Termination & Cleanup

```mermaid
sequenceDiagram
    participant Customer
    participant ACS
    participant EventHandler as Event Handler
    participant MediaHandler as Media Handler
    participant VoiceLive as Voice Live API
    participant Blob as Azure Blob Storage
    participant Session as Call Session Object

    rect rgb(255, 230, 230)
        Note over Customer,ACS: Customer Hangs Up
        Customer->>ACS: Ends call
        ACS->>EventHandler: POST /acs/callbacks/{context_id}<br/>CallDisconnected event
    end

    rect rgb(230, 255, 230)
        Note over EventHandler,VoiceLive: Close Voice Live Connection
        EventHandler->>MediaHandler: Trigger cleanup
        MediaHandler->>VoiceLive: Close WebSocket connection
        VoiceLive-->>MediaHandler: Connection closed
    end

    rect rgb(230, 230, 255)
        Note over MediaHandler,Session: Save Call Data
        MediaHandler->>Session: session.end_session()
        Session->>Session: Calculate call duration
        Session->>Session: Finalize transcript array

        Note over MediaHandler,Blob: Save Recordings
        MediaHandler->>MediaHandler: Create WAV files from<br/>audio buffers (PCM → WAV)
        MediaHandler->>Blob: Upload to call-recordings/<br/>senior-life/call-123.wav
        Blob-->>MediaHandler: Upload complete

        Note over MediaHandler,Blob: Save Transcript
        MediaHandler->>Session: session.get_transcript_json()
        Session-->>MediaHandler: JSON with timestamps,<br/>roles, text, collected info
        MediaHandler->>Blob: Upload to call-transcripts/<br/>senior-life/call-123.json
        Blob-->>MediaHandler: Upload complete
    end

    rect rgb(255, 240, 200)
        Note over MediaHandler: Cleanup Resources
        MediaHandler->>MediaHandler: Close audio buffers
        MediaHandler->>MediaHandler: Clear session state
        MediaHandler->>MediaHandler: Release WebSocket resources
    end

    EventHandler-->>ACS: Return 200 OK

    Note over Customer,Blob: Call complete - all data saved
```

---

## 8. Component Interaction Map

```mermaid
graph LR
    subgraph "Handlers Layer"
        AcsEvent[ACS Event Handler]
        AcsMedia[ACS Media Handler]
    end

    subgraph "Services Layer"
        ConfigMgr[Config Manager]
        Surname[Surname Service]
        Zipcode[ZIP Code Service]
        BizHours[Business Hours]
    end

    subgraph "Models Layer"
        CallSession[Call Session]
    end

    subgraph "External - Azure"
        ACS[Azure Communication<br/>Services]
        VoiceLive[Voice Live API]
        AppConfig[App Configuration]
        BlobStorage[Blob Storage]
    end

    ACS -->|IncomingCall events| AcsEvent
    AcsEvent -->|Answer call| ACS
    AcsEvent -->|Create| AcsMedia

    ACS <-->|Audio WebSocket| AcsMedia
    AcsMedia <-->|Audio streaming| VoiceLive

    AcsMedia -->|Get config| ConfigMgr
    AcsMedia -->|Verify surname| Surname
    AcsMedia -->|Lookup ZIP| Zipcode
    AcsMedia -->|Check hours| BizHours
    AcsMedia -->|Track state| CallSession

    ConfigMgr -->|Read config| AppConfig
    ConfigMgr -->|Read/write blobs| BlobStorage
    Surname -->|Download surnames.db| BlobStorage
    AcsMedia -->|Save recordings| BlobStorage
    AcsMedia -->|Save transcripts| BlobStorage

    BizHours -->|Use config| ConfigMgr

    style AcsEvent fill:#0078d4,color:#fff
    style AcsMedia fill:#0078d4,color:#fff
    style ConfigMgr fill:#52b788
    style Surname fill:#52b788
    style Zipcode fill:#52b788
    style BizHours fill:#52b788
    style CallSession fill:#ffa94d
    style VoiceLive fill:#ff6b6b,color:#fff
```

---

## 9. Deployment Architecture

```mermaid
graph TB
    subgraph "User Access"
        WebBrowser[Web Browser<br/>Test Client]
        Phone[Phone Calls<br/>via PSTN]
    end

    subgraph "Azure Container Apps Environment"
        ContainerApp[voice-agent-acs<br/>Container App]

        subgraph "Container Instance"
            QuartApp[Quart Server<br/>:8000]
            Handlers[Event & Media<br/>Handlers]
            Services[Business Logic<br/>Services]
        end
    end

    subgraph "Azure Communication Services"
        ACSResource[ACS Resource]
        PhoneNumber[Phone Number]
        EventGrid[Event Grid<br/>Subscription]
    end

    subgraph "Azure AI"
        AIFoundry[AI Foundry<br/>Voice Live API]
    end

    subgraph "Azure Storage & Config"
        ACR[Container Registry<br/>voiceagentsacr]
        AppConfig[App Configuration<br/>Company Configs]
        BlobStorage[Blob Storage<br/>Instructions, Data,<br/>Recordings, Transcripts]
    end

    subgraph "Azure Monitoring"
        AppInsights[Application Insights<br/>Logs & Metrics]
        LogAnalytics[Log Analytics<br/>Workspace]
    end

    Phone --> PhoneNumber
    PhoneNumber --> ACSResource
    ACSResource --> EventGrid
    EventGrid -->|Webhook| QuartApp

    WebBrowser -->|HTTPS| QuartApp

    QuartApp --> Handlers
    Handlers --> Services

    Handlers <-->|WebSocket| ACSResource
    Handlers <-->|WebSocket| AIFoundry

    Services --> AppConfig
    Services --> BlobStorage

    ACR -.->|Pull image| ContainerApp

    ContainerApp --> AppInsights
    AppInsights --> LogAnalytics

    style ContainerApp fill:#0078d4,color:#fff
    style ACSResource fill:#0078d4,color:#fff
    style AIFoundry fill:#ff6b6b,color:#fff
    style ACR fill:#ffd93d
    style AppConfig fill:#ffd93d
    style BlobStorage fill:#ffd93d
```

---

## 10. Function Calling Architecture (v20.0)

```mermaid
sequenceDiagram
    participant Customer
    participant VoiceLive as Voice Live API
    participant Handler as Media Handler
    participant Function as Function Service<br/>(Surname/ZIP)
    participant WS as Raw WebSocket<br/>(SDK Bypass)

    rect rgb(230, 240, 255)
        Note over Customer,VoiceLive: Customer provides information
        Customer->>VoiceLive: "My last name is Smith"
        VoiceLive->>Handler: input_audio_transcription.completed<br/>transcript: "Smith"
    end

    rect rgb(255, 240, 230)
        Note over VoiceLive,Handler: Voice Live decides to call function
        VoiceLive->>Handler: response.function_call_arguments.done<br/>function: verify_surname<br/>args: {surname: "Smith"}<br/>call_id: call_ABC123
        Note right of Handler: SDK Event Detection<br/>(Primary Method)
    end

    rect rgb(240, 255, 240)
        Note over Handler,Function: Execute function locally
        Handler->>Function: verify_surname("Smith")
        Function->>Function: Query 162K surnames.db<br/>Phonetic matching
        Function-->>Handler: {status: "multiple",<br/>options: ["SMITH", "SMYTH"]}
        Note right of Handler: Function executed<br/>successfully
    end

    rect rgb(255, 230, 230)
        Note over Handler,WS: SDK Bypass - Send result via raw WebSocket
        Handler->>Handler: Build raw message:<br/>{type: "conversation.item.create",<br/>item: {type: "function_call_output",<br/>call_id: "call_ABC123",<br/>output: json.dumps(result)}}
        Note right of Handler: ⚠️ SDK method broken,<br/>use raw WebSocket
        Handler->>WS: Access connection._ws or .ws
        WS->>VoiceLive: ws.send(json.dumps(raw_message))
        Note right of WS: Bypasses SDK validation,<br/>sends directly to API
    end

    rect rgb(240, 230, 255)
        Note over VoiceLive,Customer: AI uses function result in response
        VoiceLive->>VoiceLive: Process function output<br/>Generate contextual response
        VoiceLive->>Handler: response.audio.delta<br/>(AI speech audio)
        Handler->>Customer: "Is that spelled<br/>S-M-I-T-H or S-M-Y-T-H?"
    end

    Note over Customer,VoiceLive: Function calling complete - conversation continues

    style Handler fill:#52b788
    style Function fill:#ffd93d
    style WS fill:#ff6b6b,color:#fff
    style VoiceLive fill:#0078d4,color:#fff
```

---

## 11. SDK Bypass Implementation Detail

```mermaid
flowchart TD
    Start([Function executed<br/>with result]) --> BuildMsg[Build raw JSON message]

    BuildMsg --> RawMsg["raw_message = {<br/>  'type': 'conversation.item.create',<br/>  'item': {<br/>    'type': 'function_call_output',<br/>    'call_id': call_id,<br/>    'output': json.dumps(result)<br/>  }<br/>}"]

    RawMsg --> CheckWS{WebSocket<br/>accessible?}

    CheckWS -->|Yes: _ws exists| GetWS1["ws = connection._ws"]
    CheckWS -->|Yes: ws exists| GetWS2["ws = connection.ws"]
    CheckWS -->|No| Error1[❌ No WebSocket found]

    GetWS1 --> Send
    GetWS2 --> Send[Send raw message:<br/>await ws.send(json.dumps(raw_message))]

    Send --> Success[✅ Function result sent<br/>via raw WebSocket]

    Success --> API[Voice Live API<br/>receives function output]
    API --> Continue[AI continues<br/>conversation with result]

    Error1 --> Log[Log error and continue<br/>without function result]

    style Start fill:#e1f5ff
    style RawMsg fill:#fff3cd
    style Send fill:#ff6b6b,color:#fff
    style Success fill:#52b788,color:#fff
    style Error1 fill:#ff6b6b,color:#fff
    style API fill:#0078d4,color:#fff

    Note1["⚠️ SDK Limitation:<br/>ConversationRequestItem<br/>doesn't accept call_id<br/>or function_call_id"]
    Note1 -.->|Explains why| RawMsg

    Note2["🔧 Workaround:<br/>Access underlying<br/>WebSocket directly"]
    Note2 -.->|Solution| GetWS1

    style Note1 fill:#ffe6e6
    style Note2 fill:#e6ffe6
```

---

## 12. Production Monitoring & Resilience

```mermaid
flowchart TB
    subgraph "Session Lifecycle"
        Start([Call Initiated]) --> CreateMonitor[Create SessionMonitor<br/>track: tokens, turns, calls]
        CreateMonitor --> RetryLoop[Connection with<br/>Exponential Backoff]
    end

    subgraph "Connection Resilience"
        RetryLoop --> Attempt1{Attempt 1}
        Attempt1 -->|Success| Connected[✅ Connected]
        Attempt1 -->|Fail| Wait2[Wait 2s]
        Wait2 --> Attempt2{Attempt 2}
        Attempt2 -->|Success| Connected
        Attempt2 -->|Fail| Wait4[Wait 4s]
        Wait4 --> Attempt3{Attempt 3}
        Attempt3 -->|Success| Connected
        Attempt3 -->|Fail| Failed[❌ All attempts failed]
    end

    subgraph "Active Session Monitoring"
        Connected --> Heartbeat[Start Heartbeat Loop<br/>30s intervals]
        Heartbeat --> Monitor[Track Metrics:<br/>• Token usage<br/>• Turn count<br/>• Function calls<br/>• VAD triggers<br/>• Errors]
    end

    subgraph "Audio Processing"
        Monitor --> Chunking[100ms Audio Chunks<br/>2400 samples @ 24kHz]
        Chunking --> Buffer[Buffer for optimal<br/>chunk alignment]
        Buffer --> Forward[Forward to<br/>Voice Live API]
    end

    subgraph "Token Management"
        Monitor --> CheckTokens{Tokens > 64k?}
        CheckTokens -->|No| Continue[Continue call]
        CheckTokens -->|Yes| Warn[⚠️ Warning:<br/>Approaching limit]
        Warn --> CheckLimit{Tokens > 100k?}
        CheckLimit -->|No| Continue
        CheckLimit -->|Yes| Alert[🚨 HIGH USAGE:<br/>Near 128k limit]
    end

    subgraph "Cleanup & Reporting"
        Continue --> CallEnd[Call Ends]
        CallEnd --> StopHeart[Stop Heartbeat]
        StopHeart --> Summary[Log Session Summary:<br/>• Duration<br/>• Turn count<br/>• Token usage<br/>• Function calls<br/>• Errors]
        Summary --> Save[Save Recordings<br/>& Transcripts]
    end

    style CreateMonitor fill:#52b788,color:#fff
    style Connected fill:#52b788,color:#fff
    style Failed fill:#ff6b6b,color:#fff
    style Warn fill:#ffa94d
    style Alert fill:#ff6b6b,color:#fff
    style Summary fill:#b197fc,color:#fff
```

---

## Diagram Rendering

These diagrams use **Mermaid** syntax and will render automatically in:

- ✅ GitHub (in markdown files)
- ✅ GitLab
- ✅ VS Code (with Mermaid extension)
- ✅ Many markdown viewers
- ✅ Documentation sites (MkDocs, Docusaurus, etc.)

### Viewing Locally

If your markdown viewer doesn't support Mermaid:

1. **Install VS Code Mermaid Extension:**
   ```
   code --install-extension bierner.markdown-mermaid
   ```

2. **Use Online Mermaid Editor:**
   - https://mermaid.live/
   - Copy/paste diagram code to preview

3. **GitHub Preview:**
   - Push to GitHub and view there (native support)

---

## Diagram Index

| # | Diagram | Purpose |
|---|---------|---------|
| 1 | Overall System Architecture | High-level component view |
| 2 | Call Initiation Sequence | Step-by-step call setup |
| 3 | Active Call Audio Flow | Bidirectional streaming |
| 4 | Surname Verification | Phonetic matching logic |
| 5 | ZIP Code Lookup | Auto city/state confirmation |
| 6 | Business Hours Logic | Overnight hours support |
| 7 | Call Termination | Cleanup and data saving |
| 8 | Component Interaction | Service dependencies |
| 9 | Deployment Architecture | Azure resources layout |
| **10** | **Function Calling Architecture** | **Complete function call flow with SDK bypass** |
| **11** | **SDK Bypass Implementation** | **Raw WebSocket workaround details** |
| **12** | **Production Monitoring** | **SessionMonitor, retry logic, token tracking** |

---

**Note:** These diagrams complement the text descriptions in `ACS_MIGRATION_ARCHITECTURE.md`.
