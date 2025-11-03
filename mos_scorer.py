"""
MOS (Mean Opinion Score) Scorer
Objective audio quality assessment using PESQ (Perceptual Evaluation of Speech Quality).

Based on Azure S2S Voice Agent Quality Guide Section 5: Audio Quality Scoring With POLQA.

MOS Scale:
5.0 = Excellent
4.0 = Good
3.0 = Fair
2.0 = Poor
1.0 = Bad

PESQ is an open-source alternative to commercial POLQA, providing similar ITU-T P.862 compliance.
"""

import logging
import os
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger("mos_scorer")

# Try to import pesq, but make it optional
try:
    from pesq import pesq as pesq_score
    PESQ_AVAILABLE = True
except ImportError:
    PESQ_AVAILABLE = False
    logger.warning("PESQ library not available. Install with: pip install pesq")


class MOSScorer:
    """
    Objective speech quality scorer using PESQ algorithm.

    Compares reference audio (clean TTS output) against degraded audio
    (what the caller actually heard) to produce MOS score.
    """

    # Sample rates supported by PESQ
    PESQ_SAMPLE_RATES = [8000, 16000]  # Narrowband and wideband

    def __init__(self):
        """Initialize MOS scorer."""
        if not PESQ_AVAILABLE:
            logger.warning("⚠️ PESQ not available - MOS scoring disabled")
            logger.warning("   Install with: pip install pesq")

    def calculate_mos(self,
                     reference_audio: bytes,
                     degraded_audio: bytes,
                     sample_rate: int = 24000,
                     mode: str = "wb") -> Optional[float]:
        """
        Calculate MOS score by comparing reference vs degraded audio.

        Args:
            reference_audio: Clean TTS output (PCM16 bytes)
            degraded_audio: Audio as received by caller (PCM16 bytes)
            sample_rate: Original sample rate (will be resampled for PESQ if needed)
            mode: "wb" for wideband (16kHz) or "nb" for narrowband (8kHz)

        Returns:
            MOS score (1.0 - 5.0) or None if PESQ unavailable
        """
        if not PESQ_AVAILABLE:
            logger.debug("PESQ not available, skipping MOS calculation")
            return None

        try:
            # Convert bytes to numpy arrays
            ref_samples = self._bytes_to_samples(reference_audio)
            deg_samples = self._bytes_to_samples(degraded_audio)

            if ref_samples is None or deg_samples is None:
                logger.error("Failed to convert audio bytes to samples")
                return None

            # Align lengths (truncate to shorter)
            min_len = min(len(ref_samples), len(deg_samples))
            ref_samples = ref_samples[:min_len]
            deg_samples = deg_samples[:min_len]

            # Resample if needed for PESQ
            pesq_rate = 16000 if mode == "wb" else 8000

            if sample_rate != pesq_rate:
                ref_samples = self._resample(ref_samples, sample_rate, pesq_rate)
                deg_samples = self._resample(deg_samples, sample_rate, pesq_rate)

            # Calculate PESQ score
            # Note: PESQ returns score range depends on mode:
            # - Narrowband (8kHz): -0.5 to 4.5
            # - Wideband (16kHz): 1.0 to 4.5
            mos = pesq_score(pesq_rate, ref_samples, deg_samples, mode)

            # Clamp to valid MOS range (1.0 - 5.0)
            mos = max(1.0, min(5.0, mos))

            logger.info(f"📊 PESQ MOS Score: {mos:.2f}/5.0 ({self._mos_rating(mos)})")

            return float(mos)

        except Exception as e:
            logger.error(f"Error calculating PESQ MOS: {e}")
            return None

    def calculate_mos_from_files(self,
                                reference_wav_path: str,
                                degraded_wav_path: str,
                                mode: str = "wb") -> Optional[float]:
        """
        Calculate MOS score from WAV files.

        Args:
            reference_wav_path: Path to reference WAV file
            degraded_wav_path: Path to degraded WAV file
            mode: "wb" for wideband or "nb" for narrowband

        Returns:
            MOS score (1.0 - 5.0) or None if error
        """
        if not PESQ_AVAILABLE:
            return None

        try:
            import wave

            # Read reference WAV
            with wave.open(reference_wav_path, 'rb') as wf:
                ref_rate = wf.getframerate()
                ref_frames = wf.readframes(wf.getnframes())
                ref_samples = self._bytes_to_samples(ref_frames)

            # Read degraded WAV
            with wave.open(degraded_wav_path, 'rb') as wf:
                deg_rate = wf.getframerate()
                deg_frames = wf.readframes(wf.getnframes())
                deg_samples = self._bytes_to_samples(deg_frames)

            if ref_samples is None or deg_samples is None:
                return None

            # Ensure same sample rate
            if ref_rate != deg_rate:
                logger.warning(f"Sample rate mismatch: ref={ref_rate}, deg={deg_rate}")
                # Resample degraded to match reference
                deg_samples = self._resample(deg_samples, deg_rate, ref_rate)

            # Align lengths
            min_len = min(len(ref_samples), len(deg_samples))
            ref_samples = ref_samples[:min_len]
            deg_samples = deg_samples[:min_len]

            # Resample for PESQ if needed
            pesq_rate = 16000 if mode == "wb" else 8000
            if ref_rate != pesq_rate:
                ref_samples = self._resample(ref_samples, ref_rate, pesq_rate)
                deg_samples = self._resample(deg_samples, ref_rate, pesq_rate)

            # Calculate PESQ
            mos = pesq_score(pesq_rate, ref_samples, deg_samples, mode)
            mos = max(1.0, min(5.0, mos))

            logger.info(f"📊 File-based PESQ MOS: {mos:.2f}/5.0 ({self._mos_rating(mos)})")
            logger.info(f"   Reference: {os.path.basename(reference_wav_path)}")
            logger.info(f"   Degraded: {os.path.basename(degraded_wav_path)}")

            return float(mos)

        except Exception as e:
            logger.error(f"Error calculating MOS from files: {e}")
            return None

    def _bytes_to_samples(self, audio_bytes: bytes) -> Optional[np.ndarray]:
        """Convert PCM16 bytes to float samples."""
        try:
            import struct

            # Unpack 16-bit samples
            num_samples = len(audio_bytes) // 2
            samples = struct.unpack(f"<{num_samples}h", audio_bytes)

            # Convert to float (-1.0 to 1.0)
            samples_float = np.array(samples, dtype=np.float64) / 32768.0

            return samples_float

        except Exception as e:
            logger.error(f"Error converting bytes to samples: {e}")
            return None

    def _resample(self, samples: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
        """
        Resample audio to target sample rate.

        Uses simple linear interpolation. For production, consider using
        scipy.signal.resample or librosa for better quality.
        """
        if orig_rate == target_rate:
            return samples

        try:
            # Try scipy first (better quality)
            from scipy import signal
            num_samples = int(len(samples) * target_rate / orig_rate)
            resampled = signal.resample(samples, num_samples)
            return resampled

        except ImportError:
            # Fallback to numpy linear interpolation
            logger.debug("scipy not available, using numpy interpolation for resampling")

            duration = len(samples) / orig_rate
            num_samples = int(duration * target_rate)

            x_orig = np.linspace(0, len(samples) - 1, len(samples))
            x_new = np.linspace(0, len(samples) - 1, num_samples)

            resampled = np.interp(x_new, x_orig, samples)
            return resampled

    def _mos_rating(self, mos: float) -> str:
        """Convert MOS score to quality rating."""
        if mos >= 4.5:
            return "EXCELLENT"
        elif mos >= 4.0:
            return "GOOD"
        elif mos >= 3.0:
            return "FAIR"
        elif mos >= 2.0:
            return "POOR"
        else:
            return "BAD"

    def analyze_mos_drop(self,
                        reference_mos: float,
                        degraded_mos: float) -> Tuple[float, str]:
        """
        Analyze MOS degradation and diagnose root cause.

        Args:
            reference_mos: MOS of clean TTS audio
            degraded_mos: MOS of received audio

        Returns:
            (mos_drop, diagnosis)
        """
        mos_drop = reference_mos - degraded_mos

        if mos_drop < 0.3:
            diagnosis = "Minimal degradation - network path is clean"
        elif mos_drop < 0.7:
            diagnosis = "Minor degradation - slight network impact or codec artifacts"
        elif mos_drop < 1.5:
            diagnosis = "Moderate degradation - network issues (jitter/loss) or AGC problems (Guide Section 5.2)"
        else:
            diagnosis = "Severe degradation - major network issues or audio processing damage (Guide Section 5.2)"

        logger.info(f"📉 MOS Drop Analysis:")
        logger.info(f"   Reference MOS: {reference_mos:.2f}")
        logger.info(f"   Degraded MOS: {degraded_mos:.2f}")
        logger.info(f"   Drop: {mos_drop:.2f}")
        logger.info(f"   Diagnosis: {diagnosis}")

        return (mos_drop, diagnosis)

    def is_pesq_available(self) -> bool:
        """Check if PESQ library is available."""
        return PESQ_AVAILABLE

    def get_installation_instructions(self) -> str:
        """Get instructions for installing PESQ library."""
        return """
To enable MOS scoring with PESQ:

1. Install the pesq library:
   pip install pesq

2. (Optional) For better resampling quality:
   pip install scipy

3. Verify installation:
   python -c "from pesq import pesq; print('PESQ installed successfully')"

Note: PESQ is an open-source implementation of ITU-T P.862.
For commercial POLQA (ITU-T P.863), contact OPTICOM GmbH.
"""


# Convenience function for quick MOS calculation
def calculate_mos(reference_wav: str, degraded_wav: str) -> Optional[float]:
    """
    Quick MOS calculation from WAV files.

    Args:
        reference_wav: Path to reference audio
        degraded_wav: Path to degraded audio

    Returns:
        MOS score or None
    """
    scorer = MOSScorer()
    return scorer.calculate_mos_from_files(reference_wav, degraded_wav, mode="wb")


if __name__ == "__main__":
    # Test if PESQ is available
    scorer = MOSScorer()

    if scorer.is_pesq_available():
        print("✅ PESQ is installed and ready")
    else:
        print("❌ PESQ is not installed")
        print(scorer.get_installation_instructions())
