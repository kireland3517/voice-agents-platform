# Read the file
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Import datetime at the top if not already there (for tracking timing)
if 'from datetime import datetime' not in content:
    content = content.replace(
        'from typing import Optional',
        'from typing import Optional\nfrom datetime import datetime, timedelta'
    )

# 2. Add response_start_time to CallSession
content = content.replace(
    '        self.azure_has_started_speaking = False  # Prevents early barge-in',
    '        self.azure_has_started_speaking = False  # Prevents early barge-in\n        self.response_start_time = None  # Track when response started'
)

# 3. Set response_start_time when response.created fires
content = content.replace(
    '    elif event_type == "response.created":\n        if call_session:\n            call_session.azure_is_speaking = True\n            call_session.current_response_id = event.get("response", {}).get("id")',
    '    elif event_type == "response.created":\n        if call_session:\n            call_session.azure_is_speaking = True\n            call_session.current_response_id = event.get("response", {}).get("id")\n            call_session.response_start_time = datetime.utcnow()  # Track when response started'
)

# 4. Add grace period check to barge-in detection
old_bargein = '                            if call_session and call_session.azure_is_speaking and call_session.azure_has_started_speaking:'

new_bargein = '''                            # Check if Azure is speaking AND grace period has passed (3 seconds for greeting)
                            if call_session and call_session.azure_is_speaking and call_session.azure_has_started_speaking:
                                # Grace period: allow 3 seconds for greeting without interruption
                                if call_session.response_start_time:
                                    elapsed = (datetime.utcnow() - call_session.response_start_time).total_seconds()
                                    if elapsed < 3.0:
                                        # Still in grace period, don't barge-in yet
                                        continue
                                '''

content = content.replace(old_bargein, new_bargein)

# Write back
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Added 3-second grace period for greeting!")
