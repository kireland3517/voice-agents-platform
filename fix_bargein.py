import re

def fix_app_py():
    """
    Automatically comment out aggressive media-based barge-in logic in app.py
    """
    
    print("🔧 Reading app.py...")
    
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern to find the aggressive barge-in block - look for the media event handler
    # Find the section with "if call_session.azure_ws and call_session.azure_is_speaking"
    
    # Check if already fixed
    if '# DISABLED: Too aggressive' in content:
        print("✅ app.py already fixed! No changes needed.")
        return False
    
    # More flexible pattern to find the barge-in code
    pattern = r'([ \t]+# Optional: cancel mid-turn on media arrival AFTER greeting\n[ \t]+if call_session\.azure_ws and call_session\.azure_is_speaking and call_session\.greeting_done:.*?logger\.error\(f"Failed to cancel on media: \{e\}"\)\n)'
    
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("❌ Could not find the barge-in code to fix.")
        print("Looking for code containing: 'if call_session.azure_ws and call_session.azure_is_speaking'")
        
        # Try to find it manually
        if 'call_session.azure_ws and call_session.azure_is_speaking and call_session.greeting_done' in content:
            print("Found the code but pattern doesn't match exactly.")
            print("Please manually comment out the block starting with:")
            print("  'if call_session.azure_ws and call_session.azure_is_speaking'")
            print("in the 'elif evt == \"media\"' section")
        return False
    
    print("✅ Found the barge-in code!")
    
    old_code = match.group(1)
    
    # Comment out each line
    lines = old_code.split('\n')
    commented_lines = []
    
    # Add explanation
    first_line = lines[0]
    indent = len(first_line) - len(first_line.lstrip())
    
    explanation = ' ' * indent + '# DISABLED: Too aggressive - media packets arrive constantly, even during silence\n'
    explanation += ' ' * indent + '# The speech_started handler with proper VAD (0.7 threshold, 700ms silence) handles barge-in correctly\n'
    
    for line in lines:
        if line.strip():
            indent = len(line) - len(line.lstrip())
            commented_lines.append(' ' * indent + '# ' + line.lstrip())
        else:
            commented_lines.append(line)
    
    new_code = explanation + '\n'.join(commented_lines)
    content = content.replace(old_code, new_code)
    
    # Update version number
    content = re.sub(
        r'"version": "[^"]*"',
        '"version": "12.3 - VAD-only barge-in"',
        content,
        count=1
    )
    
    print("💾 Writing fixed app.py...")
    
    # Backup original
    with open('app.py.backup', 'w', encoding='utf-8') as f:
        with open('app.py', 'r', encoding='utf-8') as orig:
            f.write(orig.read())
    print("📋 Backup saved as app.py.backup")
    
    # Write fixed version
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ app.py has been fixed!")
    print("\nChanges made:")
    print("  ✓ Commented out aggressive media-based barge-in logic")
    print("  ✓ Updated version to 12.3")
    print("  ✓ Created backup (app.py.backup)")
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("🔧 Cedar Voice Agent - Barge-in Fix Script")
    print("=" * 60)
    
    try:
        changed = fix_app_py()
        
        if changed:
            print("\n" + "=" * 60)
            print("🚀 Next Steps:")
            print("=" * 60)
            print("\n1. Review the changes in app.py")
            print("2. Run deployment:")
            print("   az acr build --registry voiceagentsenvironmentf2c46d --image voice-agent-bridge:v12.3 .")
            print("   az containerapp update --name voice-agents-bridge --resource-group voice_agents --image voiceagentsenvironmentf2c46d.azurecr.io/voice-agent-bridge:v12.3")
            print("\n3. Test by calling the number")
            print("\n✨ Cedar should now complete her responses without being cut off!")
        
    except FileNotFoundError:
        print("❌ Error: app.py not found in current directory")
        print("Make sure you're running this from the project root directory")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
