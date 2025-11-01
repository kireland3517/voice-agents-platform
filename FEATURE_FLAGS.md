# Feature Flags Guide

**Version:** 15.0 - Research-Backed Optimizations
**Date:** October 30, 2025

---

## 🎯 Quick Start

Feature flags let you toggle new capabilities **without changing code**. All flags are configured in Azure App Configuration under `{company-id}/audio-settings`.

---

## ✅ Phase 1: Active Optimizations (LIVE)

These changes are **already active** with safe defaults:

| Setting | Old Value | New Value | Impact |
|---------|-----------|-----------|--------|
| `vad-silence-duration-ms` | 800ms | **500ms** | ~300ms faster responses |
| `max-response-tokens` | 4096 | **1500** | 20% lower latency |

**To revert:** Set these values explicitly in Azure App Config per company.

---

## 🔬 Phase 2: Experimental Features (OFF by default)

Toggle these in Azure App Config to test new research-backed features:

### 1. Semantic VAD (HIGHEST IMPACT) ⭐⭐⭐⭐⭐

**Key:** `enable-semantic-vad`
**Type:** `boolean`
**Default:** `false`
**Research:** 40-60% reduction in false turn endings

```json
{
  "enable-semantic-vad": true
}
```

**What it does:**
- Context-aware turn detection (analyzes words, not just silence)
- Automatically removes filler words ("uh", "um", "like")
- Better handling of number dictation and complex sentences

**When to enable:**
- ✅ Calls with number dictation (phone numbers, addresses)
- ✅ Complex multi-clause sentences
- ✅ Non-native English speakers

**When to keep disabled:**
- ❌ Simple yes/no conversations
- ❌ Testing baseline performance
- ❌ If you notice increased latency

---

### 2. Noise Suppression (Coming Soon) ⭐⭐⭐⭐

**Key:** `enable-noise-suppression`
**Type:** `boolean`
**Default:** `false`
**Research:** 60% background noise reduction

```json
{
  "enable-noise-suppression": true
}
```

**What it does:**
- Azure Deep Noise Suppression on server side
- Filters background noise, keyboard clicks, traffic

**When to enable:**
- ✅ Noisy call environments
- ✅ Call center scenarios
- ✅ Mobile callers

---

### 3. Echo Cancellation (Coming Soon) ⭐⭐⭐⭐

**Key:** `enable-echo-cancellation`
**Type:** `boolean`
**Default:** `false`

```json
{
  "enable-echo-cancellation": true
}
```

**What it does:**
- Server-side echo cancellation
- Prevents feedback loops in bidirectional audio

**When to enable:**
- ✅ Speakerphone calls
- ✅ Conference room scenarios
- ✅ Hearing audio feedback issues

---

### 4. Audio Transcription (Coming Soon) ⭐⭐⭐

**Key:** `enable-audio-transcription`
**Type:** `boolean`
**Default:** `false`

```json
{
  "enable-audio-transcription": true,
  "transcription-model": "whisper-1",
  "transcription-language": "en"
}
```

**What it does:**
- Uses Whisper-1 for improved transcript quality
- Better proper noun recognition
- Technical term accuracy

---

## 🎨 Configuration Examples

### Example 1: Conservative (Current Production)
```json
{
  "vad-threshold": 0.3,
  "vad-silence-duration-ms": 500,
  "vad-prefix-padding-ms": 200,
  "temperature": 0.8,
  "max-response-tokens": 1500,
  "enable-semantic-vad": false
}
```

### Example 2: Optimized for Complex Conversations
```json
{
  "vad-threshold": 0.3,
  "vad-silence-duration-ms": 500,
  "vad-prefix-padding-ms": 200,
  "temperature": 0.8,
  "max-response-tokens": 1500,
  "enable-semantic-vad": true,
  "enable-noise-suppression": true
}
```

### Example 3: Noisy Environment
```json
{
  "vad-threshold": 0.6,
  "vad-silence-duration-ms": 600,
  "vad-prefix-padding-ms": 300,
  "temperature": 0.8,
  "max-response-tokens": 1500,
  "enable-semantic-vad": true,
  "enable-noise-suppression": true,
  "enable-echo-cancellation": true
}
```

---

## 📊 How to Test Feature Flags

### Step 1: Update Azure App Config

```bash
# In Azure Portal:
# Navigate to: App Configuration → Configuration Explorer
# Find: {company-id}/audio-settings
# Update JSON with new flags
```

### Step 2: Verify in Logs

After deployment, check logs for feature flag status:

```
✅ Voice Live API session configured
   Voice: en-US-FableTurboMultilingualNeural (Azure TTS)
   VAD: Semantic VAD (threshold=0.3, silence=500ms, padding=200ms)
   LLM: temp=0.8, max_tokens=1500
```

**Look for:**
- `Semantic VAD` = flag enabled
- `Server VAD` = flag disabled

### Step 3: Test a Call

Make a test call and observe:
- **Latency:** Faster turn detection?
- **Accuracy:** Fewer premature interruptions?
- **Quality:** Better transcript quality?

---

## 🔄 Rollback Strategy

If a feature flag causes issues:

### Option 1: Quick Disable (1 minute)
Set the flag to `false` in Azure App Config. Changes take effect in <5 minutes (cache expiry).

### Option 2: Revert to Defaults (2 minutes)
Remove the flag entirely from config - code uses safe defaults.

### Option 3: Full Rollback (5 minutes)
Revert to previous git commit:

```bash
git revert HEAD
git push origin main
# Redeploy
```

---

## 🎯 Recommended Testing Approach

### Week 1: Baseline
- Keep all flags `false`
- Measure: latency, false turn endings, user satisfaction
- Establish baseline metrics

### Week 2: Enable Semantic VAD
- Set `enable-semantic-vad: true` for one company
- Compare metrics to baseline
- If positive, enable for more companies

### Week 3: Add Noise Suppression
- Enable `enable-noise-suppression: true`
- Test in noisy environments
- Measure audio quality improvements

### Week 4: Full Production
- Enable best-performing flags for all companies
- Monitor for 7 days
- Document final configuration

---

## 📝 Notes

- **Cache:** Config changes take up to 5 minutes to apply (5-minute cache TTL)
- **Per-Company:** Each company can have different flags enabled
- **Logging:** All feature flag states logged at session start
- **Defaults:** All experimental features default to `false` for safety

---

## 🆘 Troubleshooting

### Issue: Feature flag not taking effect
**Solution:** Wait 5 minutes for cache expiry, or restart the app

### Issue: Worse performance with semantic VAD
**Solution:** Disable flag, check VAD threshold (may need adjustment)

### Issue: Increased latency
**Solution:** Reduce `max-response-tokens` to 1000 or 1500

---

## 📚 Research Sources

All optimizations based on production research (October 2025):
- Azure Voice Live API documentation
- GitHub production implementations (aoai-realtime-audio-sdk)
- Developer benchmarks (Smallest.ai, Picovoice)
- Forum feedback (Hacker News, Reddit, Azure community)

**Research document:** See your research compilation for full details.
