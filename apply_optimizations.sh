#!/bin/bash
# apply_optimizations.sh - Apply all optimizations and fixes

echo "🚀 Applying all optimizations and fixes..."

# 1. Fix function call result handling
echo "📝 Fixing function call result handling..."
cat > function_fix.patch << 'EOF'
--- a/app.py
+++ b/app.py
@@ -475,14 +475,18 @@
             if function_name and arguments:
                 # Track function call
                 if monitor:
                     monitor.add_function_call(function_name)
                 
                 # Execute the function
                 result = await execute_function(function_name, arguments)
                 logger.info(f"   Function result: {result}")
                 
                 # Send result back to Voice Live
                 try:
-                    # Try SDK method first
-                    if hasattr(voicelive_connection, 'conversation') and hasattr(voicelive_connection.conversation, 'item'):
-                        await voicelive_connection.conversation.item.create({
-                            "type": "function_call_output",
-                            "call_id": call_id,
-                            "output": json.dumps(result)
-                        })
+                    # Create function output item using correct SDK method
+                    await voicelive_connection.conversation.item.create(
+                        event_id=f"func_result_{call_id}",
+                        type="function_call_output",
+                        call_id=call_id,
+                        output=json.dumps(result)
+                    )
                     logger.info("✅ Function result sent via SDK")
EOF
patch -p1 < function_fix.patch

# 2. Fix "DEMO MODE" message
echo "📝 Updating connection message..."
sed -i 's/🚀 DEMO MODE - Connecting to Azure Voice Live API with ALL features/🚀 Connecting to Azure Voice Live API with ALL optimizations enabled/g' app.py

# 3. Update max tokens to optimal value
echo "📝 Setting optimal max tokens (1500)..."
sed -i "s/audio_settings\['max-response-tokens'\] = 4096/audio_settings['max-response-tokens'] = 1500/g" config.py

# 4. Commit changes
echo "📦 Committing changes to git..."
git add -A
git commit -m "Optimizations: Fix function calls, update messaging, optimize tokens"
git push origin main

echo "✅ All changes applied and committed!"
echo ""
echo "🚀 Now deploying to Azure..."

# 5. Deploy to Azure
az acr build \
  --registry voiceagentsenvironmentf2c46d \
  --image voice-agent-signalwire:latest \
  --file Dockerfile .

# 6. Update container app
az containerapp update \
  --name voice-agents-bridge \
  --resource-group voice_agents \
  --set-env-vars "OPTIMIZATION_DEPLOY=$(date +%s)"

echo "✅ Deployment complete!"
echo ""
echo "📊 To monitor logs:"
echo "az containerapp logs show --name voice-agents-bridge --resource-group voice_agents --follow"
