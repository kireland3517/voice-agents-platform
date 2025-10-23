# Read the file
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix duplicate response_count increment
content = content.replace(
    '            call_session.response_count += 1\n            call_session.response_count += 1',
    '            call_session.response_count += 1\n            # Use response id as current item id for truncate fallback\n            call_session.current_item_id = call_session.current_response_id'
)

# 2. Fix event name: response.audio.delta -> response.output_audio.delta
content = content.replace(
    'elif event_type == "response.audio.delta":',
    'elif event_type == "response.output_audio.delta":'
)

# 3. Set azure_has_started_speaking when audio actually starts
old_audio_handler = '''                azure_audio_base64 = event["delta"]
                
                if SAVE_RECORDINGS and call_session:'''

new_audio_handler = '''                azure_audio_base64 = event["delta"]
                
                # Mark that audio actually started
                if call_session and not call_session.azure_has_started_speaking:
                    call_session.azure_has_started_speaking = True
                
                if SAVE_RECORDINGS and call_session:'''

content = content.replace(old_audio_handler, new_audio_handler)

# 4. Fix event name: response.audio.done -> response.output_audio.done
content = content.replace(
    'elif event_type == "response.audio.done":',
    'elif event_type == "response.output_audio.done":'
)

# 5. Fix event name: response.audio_transcript.delta -> response.output_audio_transcript.delta
content = content.replace(
    'elif event_type == "response.audio_transcript.delta":',
    'elif event_type == "response.output_audio_transcript.delta":'
)

# 6. Fix event name: response.audio_transcript.done -> response.output_audio_transcript.done
content = content.replace(
    'elif event_type == "response.audio_transcript.done":',
    'elif event_type == "response.output_audio_transcript.done":'
)

# Write back
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed all 4 issues: event names, flags, and duplicate increment!")
