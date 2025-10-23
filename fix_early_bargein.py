# Read the file
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add azure_has_started_speaking flag to CallSession.__init__
content = content.replace(
    '        # Barge-in detection\n        self.azure_is_speaking = False',
    '        # Barge-in detection\n        self.azure_is_speaking = False\n        self.azure_has_started_speaking = False  # Prevents early barge-in'
)

# 2. Set the flag when Azure actually starts outputting audio (in response.audio.delta)
old_audio_delta = '''                # Capture item_id for potential truncation
                if call_session and "item_id" in event:
                    call_session.current_item_id = event["item_id"]'''

new_audio_delta = '''                # Capture item_id for potential truncation
                if call_session:
                    if "item_id" in event:
                        call_session.current_item_id = event["item_id"]
                    # Mark that Azure has started speaking (prevents premature barge-in)
                    call_session.azure_has_started_speaking = True'''

content = content.replace(old_audio_delta, new_audio_delta)

# 3. Update barge-in detection to check the flag
content = content.replace(
    '                            if call_session and call_session.azure_is_speaking:',
    '                            if call_session and call_session.azure_is_speaking and call_session.azure_has_started_speaking:'
)

# Write back
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed early barge-in detection!")
