# SignalWire Caller ID Configuration

## Overview

This document explains how to pass caller ID information from SignalWire to Azure AI Voice Live through the voice-agents-bridge application.

## The Problem

When SignalWire receives a call with SIP headers (like `P-Asserted-Identity`), these headers are not automatically passed through the WebSocket Media Stream to your application. The basic `from` field only contains the SignalWire caller ID, not the original SIP header values.

## The Solution

Use SignalWire's `customParameters` in your SWML configuration to explicitly pass caller ID information through the WebSocket connection.

## SWML Configuration

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

1. **Extract caller ID** from `customParameters` with priority:
   - `customParameters.caller_id` (highest priority)
   - `customParameters.original_caller` (P-Asserted-Identity fallback)
   - `start.from` (basic SignalWire caller ID fallback)

2. **Normalize the format** to E.164:
   - Handles `tel:+1234567890`
   - Handles `sip:+1234567890@domain`
   - Handles `<sip:+1234567890@domain>`
   - Handles plain `+1234567890`
   - Adds `+1` prefix for 10-digit US numbers

3. **Pass to Azure AI** in the session context as "Caller ID: +1234567890"

## Verification

After deploying your SWML changes, make a test call and check the logs:

```
📞 Raw caller ID: tel:+12345678901
📞 Normalized caller ID: +12345678901
📞 Caller ID: +12345678901
```

The normalized caller ID will be included in the Azure AI session context for the agent to reference.

## Troubleshooting

### Caller ID shows as "None" in logs

**Problem:** The application is not receiving caller ID information.

**Solutions:**
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
