# SignalWire Caller ID Configuration

## Overview

This document explains how to pass caller ID information from SignalWire to Azure AI Voice Live through the voice-agents-bridge application.

## The Problem

When SignalWire receives a call with SIP headers (like `P-Asserted-Identity`), these headers are not automatically passed through the WebSocket Media Stream to your application. The basic `from` field only contains the SignalWire caller ID, not the original SIP header values.

## Solutions

The application supports **two methods** for passing caller ID:

1. **cXML (TwiML Compatibility XML)** - Query parameters in the WebSocket URL
2. **SWML** - Custom parameters in the stream configuration

---

## Method 1: cXML with Query Parameters (Recommended for TwiML Users)

### Configuration

Add query parameters to your Stream URL in the cXML response:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://voice-agents-bridge.victoriouswave-f95f67ff.eastus2.azurecontainerapps.io/voice/senior-life?caller_id={From}"
            codec="L16@24000h" />
  </Connect>
</Response>
```

### Available Variables

SignalWire/Twilio TwiML supports these variables:
- `{From}` - Caller's phone number
- `{To}` - Dialed number
- `{CallSid}` - Unique call identifier

### Multiple Parameters

You can pass multiple parameters:

```xml
<Stream url="wss://your-app.com/voice/company-id?caller_id={From}&amp;call_sid={CallSid}"
        codec="L16@24000h" />
```

**Note:** Use `&amp;` instead of `&` in XML.

---

## Method 2: SWML Configuration

### Basic Setup (Recommended)

```yaml
version: "1.0.0"
sections:
  main:
    # Stream audio to your application with caller ID in customParameters
    - stream_audio:
        url: "wss://your-voice-bridge-app.azurecontainerapps.io/media"
        custom_parameters:
          caller_id: "${call.from}"
```

### With Azure Voice Live Integration

If you're also forwarding the call to Azure via SIP:

```yaml
version: "1.0.0"
sections:
  main:
    # Forward to Azure with SIP headers
    - connect:
        to: "sip:proj_XXXXXXXX@eastus2.sip.ai.azure.com;transport=tls"
        headers:
          - name: "P-Asserted-Identity"
            value: "tel:${call.from}"
          - name: "Remote-Party-ID"
            value: "tel:${call.from};party=calling;screen=yes;privacy=off"
          - name: "X-From-Number"
            value: "${call.from}"

    # Stream audio with caller ID
    - stream_audio:
        url: "wss://your-voice-bridge-app.azurecontainerapps.io/media"
        custom_parameters:
          caller_id: "${call.from}"
```

### Advanced: Capturing P-Asserted-Identity

If you receive calls with `P-Asserted-Identity` headers and want to preserve them:

```yaml
version: "1.0.0"
sections:
  main:
    - stream_audio:
        url: "wss://your-voice-bridge-app.azurecontainerapps.io/media"
        custom_parameters:
          caller_id: "${call.from}"
          original_caller: "${call.headers.p-asserted-identity}"
```

## Application Code

The voice-agents-bridge application will automatically:

1. **Extract caller ID** with priority:
   - **Query parameters** from URL: `?caller_id=xxx` or `?from=xxx` (highest priority - cXML)
   - `customParameters.caller_id` (SWML custom_parameters)
   - `customParameters.original_caller` (P-Asserted-Identity from SWML)
   - `start.from` (basic SignalWire caller ID fallback)

2. **Normalize the format** to E.164:
   - Handles `tel:+1234567890`
   - Handles `sip:+1234567890@domain`
   - Handles `<sip:+1234567890@domain>`
   - Handles plain `+1234567890`
   - Adds `+1` prefix for 10-digit US numbers

3. **Pass to Azure AI** in the session context as "Caller ID: +1234567890"

## Verification

After deploying your cXML or SWML changes, make a test call and check the logs:

### cXML (Query Parameters)
```
✅ SignalWire connection accepted for company: senior-life (Caller ID from URL: +12345678901)
📞 Raw caller ID: +12345678901
📞 Caller ID source: URL query parameter
📞 Normalized caller ID: +12345678901
```

### SWML (Custom Parameters)
```
✅ SignalWire connection accepted for company: senior-life
📞 Raw caller ID: tel:+12345678901
📞 Caller ID source: SWML customParameters
📞 Normalized caller ID: +12345678901
```

The normalized caller ID will be included in the Azure AI session context for the agent to reference.

## Troubleshooting

### Caller ID shows as "None" in logs

**Problem:** The application is not receiving caller ID information.

**Solutions:**

**For cXML users:**
1. Verify your cXML includes `?caller_id={From}` in the Stream URL
2. Check that you're using `{From}` (with curly braces) not `$From`
3. Ensure your cXML is deployed as the webhook URL for your SignalWire number

**For SWML users:**
1. Verify your SWML includes `custom_parameters` with `caller_id`
2. Check that you're using `${call.from}` variable syntax correctly
3. Ensure your SWML is deployed and active on your SignalWire number

### Caller ID is in wrong format

**Problem:** The caller ID is not normalized to E.164 format.

**Solutions:**
1. The normalization function assumes US/Canada (+1) for 10-digit numbers
2. For international numbers, ensure they include the country code
3. Update the `normalize_caller_id()` function in `app.py` if you need different logic

### P-Asserted-Identity not working

**Problem:** The `original_caller` parameter is empty.

**Solutions:**
1. Verify the incoming SIP call includes `P-Asserted-Identity` header
2. Check SignalWire's SIP trunk configuration
3. Use `${call.headers.p-asserted-identity}` in SWML
4. Test with `${call.from}` first to confirm basic functionality

## Related Files

- **Application code:** `app.py` (lines 133-163 and 1443-1463)
- **Caller ID normalization:** `normalize_caller_id()` function
- **Azure context injection:** Lines 1515-1522

## Support

For SignalWire SWML syntax and variables:
- [SignalWire SWML Documentation](https://developer.signalwire.com/compatibility-api/xml/swml/)
- [SignalWire Call Variables](https://developer.signalwire.com/compatibility-api/reference/swml/variables/)
