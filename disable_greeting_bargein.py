# Read the file
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add a simple counter to CallSession to track responses
content = content.replace(
    '        self.azure_has_started_speaking = False  # Prevents early barge-in',
    '        self.azure_has_started_speaking = False  # Prevents early barge-in\n        self.response_count = 0  # Track number of responses'
)

# 2. Increment counter when response starts
content = content.replace(
    '    elif event_type == "response.created":\n        if call_session:\n            call_session.azure_is_speaking = True\n            call_session.current_response_id = event.get("response", {}).get("id")',
    '    elif event_type == "response.created":\n        if call_session:\n            call_session.azure_is_speaking = True\n            call_session.current_response_id = event.get("response", {}).get("id")\n            call_session.response_count += 1'
)

# 3. Only allow barge-in AFTER the first response (greeting)
content = content.replace(
    '                            if call_session and call_session.azure_is_speaking and call_session.azure_has_started_speaking:',
    '                            # Only allow barge-in after first response (let greeting finish)\n                            if call_session and call_session.azure_is_speaking and call_session.azure_has_started_speaking and call_session.response_count > 1:'
)

# Write back
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Disabled barge-in during first response (greeting)!")
