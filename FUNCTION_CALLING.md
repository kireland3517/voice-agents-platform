# Function Calling Architecture - Azure Voice Live API

**Version:** 20.0
**Date:** November 1, 2025
**Status:** Production - SDK Bypass Implementation

---

## Overview

This document describes how function calling works in our Azure Voice Live API integration, including the SDK workaround required for production functionality.

---

## The Problem: SDK Limitations

### What We Discovered

The Azure Voice Live Python SDK (`azure-ai-voicelive` v1.0.0) has **incomplete function calling support**:

1. ✅ Function **detection** works (SDK properly receives `response.function_call_arguments.done` events)
2. ✅ Function **execution** works (our Python functions execute correctly)
3. ❌ Function **output submission** FAILS (SDK rejects both `call_id` and `function_call_id` parameters)

### The Error

```python
# SDK Method (BROKEN):
await voicelive_connection.conversation.item.create(
    item={
        "type": "function_call_output",
        "call_id": call_id,  # ❌ SDK rejects this
        "output": json.dumps(result)
    }
)

# Error:
TypeError: ConversationRequestItem.__init__() got an unexpected keyword argument 'call_id'
```

**Root Cause:** The SDK's `ConversationRequestItem` model validation doesn't recognize the function calling parameters that the API itself supports.

---

## The Solution: Raw WebSocket Bypass

### Implementation

We bypass the SDK entirely and send raw WebSocket messages directly to the Voice Live API:

```python
# Build the raw message format (bypassing SDK)
raw_message = {
    "type": "conversation.item.create",
    "item": {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result)
    }
}

# Send directly via the WebSocket connection
if hasattr(voicelive_connection, '_ws') or hasattr(voicelive_connection, 'ws'):
    ws = getattr(voicelive_connection, '_ws', None) or getattr(voicelive_connection, 'ws', None)
    if ws:
        await ws.send(json.dumps(raw_message))
        logger.info("✅ Function result sent via raw WebSocket")
```

### Why This Works

1. The Azure Voice Live **API** fully supports function calling
2. The SDK creates a WebSocket connection underneath
3. We access that WebSocket directly (`_ws` or `ws` attribute)
4. We send the properly formatted JSON message the API expects
5. The API receives and processes the function output correctly

---

## Complete Function Calling Flow

### 1. Function Declaration (Session Setup)

```python
# Define tools using FunctionTool SDK class (this part works)
tools = [
    FunctionTool(
        name="verify_surname",
        description="Verify the spelling of a customer's surname using phonetic matching database.",
        parameters={
            "type": "object",
            "properties": {
                "surname": {
                    "type": "string",
                    "description": "The surname to verify (as heard from customer speech)"
                }
            },
            "required": ["surname"]
        }
    ),
    FunctionTool(
        name="lookup_zipcode",
        description="Get the city and state for a given ZIP code.",
        parameters={
            "type": "object",
            "properties": {
                "zipcode": {
                    "type": "string",
                    "description": "5-digit US ZIP code"
                }
            },
            "required": ["zipcode"]
        }
    )
]

# Configure session with tools
session_config = RequestSession(
    modalities=[Modality.TEXT, Modality.AUDIO],
    instructions=company_instructions,
    voice=voice_config,
    tools=tools,
    tool_choice="auto"
)
```

### 2. Function Detection (Two Methods)

#### Method 1: SDK Event Handler (Primary)

```python
# Voice Live SDK fires proper events
if event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
    function_name = event.name
    arguments = json.loads(event.arguments)
    call_id = event.call_id

    logger.info(f"🔧 Function call: {function_name} with args: {arguments}")
```

#### Method 2: Raw Event Data (Fallback)

```python
# Parse raw WebSocket data
elif hasattr(event, '_raw') or hasattr(event, 'data'):
    raw_data = getattr(event, '_raw', None) or getattr(event, 'data', None)
    if raw_data and isinstance(raw_data, str):
        parsed = json.loads(raw_data)
        if parsed.get('type') == 'response.function_call_arguments.done':
            function_name = parsed.get('name')
            arguments = json.loads(parsed.get('arguments', '{}'))
            call_id = parsed.get('call_id')
```

### 3. Function Execution

```python
async def execute_function(function_name: str, arguments: dict):
    """Execute the requested function"""
    if function_name == "verify_surname":
        surname = arguments.get("surname")
        result = SurnameService.verify_surname(surname)
        logger.info(f"   Surname verification: {result}")
        return result

    elif function_name == "lookup_zipcode":
        zipcode = arguments.get("zipcode")
        result = ZipcodeService.lookup(zipcode)
        logger.info(f"   ZIP lookup: {result}")
        return result

    else:
        return {"error": f"Unknown function: {function_name}"}
```

### 4. Function Output Submission (Raw WebSocket)

```python
# Execute the function
result = await execute_function(function_name, arguments)

# Build raw WebSocket message (bypassing SDK)
raw_message = {
    "type": "conversation.item.create",
    "item": {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result)
    }
}

# Send directly via WebSocket
ws = getattr(voicelive_connection, '_ws', None) or getattr(voicelive_connection, 'ws', None)
if ws:
    await ws.send(json.dumps(raw_message))
    logger.info("✅ Function result sent via raw WebSocket")
```

### 5. AI Processes Result

The Voice Live API receives the function output and continues the conversation:

```
Customer: "My last name is Smith"
→ Function called: verify_surname("Smith")
→ Function returns: {"status": "multiple", "options": ["SMITH", "SMITHI", "SMIT"]}
→ AI responds: "Is that spelled S-M-I-T-H, or perhaps S-M-I-T-H-I?"
```

---

## Available Functions

### 1. verify_surname

**Purpose:** Verify customer surname spelling using phonetic matching

**Input:**
```json
{
  "surname": "Smith"
}
```

**Output (Perfect Match):**
```json
{
  "status": "verified",
  "surname": "SMITH",
  "spelling": "S-M-I-T-H",
  "message": "Exact match found"
}
```

**Output (Multiple Matches):**
```json
{
  "status": "multiple",
  "options": [
    {"surname": "SMITH", "spelling": "S-M-I-T-H"},
    {"surname": "SMYTH", "spelling": "S-M-Y-T-H"}
  ],
  "message": "Multiple possible spellings"
}
```

**Database:** 162,000 surnames with Double Metaphone phonetic keys

### 2. lookup_zipcode

**Purpose:** Validate and confirm ZIP code with city/state

**Input:**
```json
{
  "zipcode": "22030"
}
```

**Output (Found):**
```json
{
  "found": true,
  "zipcode": "22030",
  "city": "Fairfax",
  "state": "Virginia",
  "message": "Fairfax, Virginia"
}
```

**Output (Not Found):**
```json
{
  "found": false,
  "zipcode": "99999",
  "message": "ZIP code not found"
}
```

**Database:** 40,000+ US ZIP codes from CSV

---

## Implementation Locations

### Function Detection & Execution
**File:** `app.py`
**Function:** `handle_voicelive_event()`
**Lines:** ~960-1060

### Function Definitions
**File:** `app.py`
**Function:** `create_voicelive_connection()`
**Lines:** ~456-488

### Surname Service
**File:** `surname_verifier.py`
**Class:** `SurnameService`

### ZIP Code Service
**File:** `zipcode_service.py`
**Class:** `ZipcodeService`

---

## Monitoring & Debugging

### Log Messages

```
# Function call detected
🔧 Function call event detected: response.function_call_arguments.done
   Function: verify_surname, Args: {'surname': 'Smith'}, CallID: call_ABC123

# Function execution
🔧 Executing function: verify_surname with args: {'surname': 'Smith'}
   Surname verification: 46 candidates found
   Function result: {'status': 'multiple', ...}

# Function output sent
✅ Function result sent via raw WebSocket

# Success indicator
📝 USER TRANSCRIPT: [AI response using the function result]
```

### Common Issues

**Issue:** `❌ No WebSocket attribute found`
- **Cause:** SDK version changed attribute name
- **Fix:** Check SDK source for WebSocket attribute name

**Issue:** Function executes but AI doesn't use result
- **Cause:** Message format incorrect
- **Fix:** Verify JSON structure matches API spec

**Issue:** `ConversationRequestItem.__init__() got an unexpected keyword argument`
- **Cause:** Using SDK method instead of raw WebSocket
- **Fix:** Ensure using raw WebSocket bypass

---

## Future SDK Updates

When the Azure Voice Live SDK adds proper function calling support:

### What to Change

1. **Remove raw WebSocket code**
2. **Use SDK methods:**
   ```python
   await voicelive_connection.conversation.item.create(
       item=FunctionCallOutputItem(
           call_id=call_id,
           output=json.dumps(result)
       )
   )
   ```

### How to Test

1. Monitor SDK changelog for function calling fixes
2. Test SDK method in development
3. If successful, remove raw WebSocket bypass
4. Deploy and verify in production

---

## References

- [Azure Voice Live API Documentation](https://learn.microsoft.com/azure/ai-services/openai/realtime-audio)
- [SDK GitHub Repository](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/ai/azure-ai-voicelive)
- [Function Calling Specification](https://platform.openai.com/docs/guides/function-calling)

---

**Last Updated:** November 1, 2025
**Implementation Version:** 20.0
**Status:** Production - Fully Functional via SDK Bypass
