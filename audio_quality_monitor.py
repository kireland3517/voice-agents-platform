"""
Audio Quality Monitor
Analyzes real-time audio metrics to detect robotic/metallic sound quality issues.

Based on Azure S2S Voice Agent Quality Guide recommendations.
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import struct

logger = logging.getLogger("audio_quality_monitor")


@dataclass
class AudioMetrics:
    """Real-time audio quality metrics for a single audio chunk."""
    timestamp: datetime
    rms_level: float  # Root Mean Square level (loudness)
    peak_level: float  # Peak amplitude
    noise_floor: float  # Estimated background noise level
    snr: float  # Signal-to-Noise Ratio in dB
    clipping_detected: bool  # True if audio is clipping/distorting
    zero_crossing_rate: float  # Measure of frequency content
    dynamic_range: float  # Difference between peak and RMS


@dataclass
class AudioQualitySession:
    """Aggregate audio quality metrics for an entire call session."""
    session_id: str
    start_time: datetime
    chunk_count: int = 0

    # Running statistics
    avg_rms: float = 0.0
    avg_snr: float = 0.0
    avg_dynamic_range: float = 0.0

    # Quality issues
    clipping_events: int = 0
    low_snr_events: int = 0  # SNR < 20 dB
    level_warnings: int = 0  # Too loud or too quiet

    # Individual chunk metrics
    metrics_history: List[AudioMetrics] = field(default_factory=list)

    # MOS estimation (1.0 - 5.0 scale, updated after analysis)
    estimated_mos: Optional[float] = None

    # Quality flags
    has_quality_issues: bool = False
    issue_summary: List[str] = field(default_factory=list)


class AudioQualityMonitor:
    """
    Monitors audio quality in real-time by analyzing PCM16 audio chunks.

    Detects issues like:
    - Clipping/distortion
    - Low signal-to-noise ratio
    - Inconsistent audio levels (AGC problems)
    - Frequency content issues
    """

    # Thresholds based on telephony best practices
    CLIPPING_THRESHOLD = 0.95  # 95% of max amplitude
    MIN_SNR_DB = 20.0  # Below this = quality warning
    GOOD_SNR_DB = 30.0  # Above this = good quality
    MIN_RMS_LEVEL = 0.01  # Below this = too quiet
    MAX_RMS_LEVEL = 0.7  # Above this = too loud (risk of clipping)

    # Audio format constants (matching your Voice Live API config)
    SAMPLE_RATE = 24000  # 24kHz
    SAMPLE_WIDTH = 2  # 16-bit PCM
    CHANNELS = 1  # Mono
    MAX_AMPLITUDE = 32768.0  # 2^15 for 16-bit audio

    def __init__(self, session_id: str):
        """Initialize audio quality monitor for a call session."""
        self.session = AudioQualitySession(
            session_id=session_id,
            start_time=datetime.utcnow()
        )

        # Rolling window for noise floor estimation
        self._noise_window: List[float] = []
        self._noise_window_size = 10  # Last 10 chunks

        logger.info(f"🎵 AudioQualityMonitor initialized for session {session_id}")

    def analyze_chunk(self, audio_bytes: bytes, source: str = "ai") -> AudioMetrics:
        """
        Analyze a single audio chunk (PCM16 format).

        Args:
            audio_bytes: Raw PCM16 audio data
            source: "ai" or "caller" to differentiate streams

        Returns:
            AudioMetrics object with quality measurements
        """
        if not audio_bytes or len(audio_bytes) < 2:
            logger.warning("Empty or invalid audio chunk received")
            return None

        # Convert bytes to numpy array of floats (-1.0 to 1.0)
        samples = self._bytes_to_normalized_samples(audio_bytes)

        if len(samples) == 0:
            return None

        # Calculate metrics
        rms = self._calculate_rms(samples)
        peak = self._calculate_peak(samples)
        noise_floor = self._estimate_noise_floor(samples)
        snr = self._calculate_snr(rms, noise_floor)
        clipping = self._detect_clipping(samples)
        zcr = self._calculate_zero_crossing_rate(samples)
        dynamic_range = self._calculate_dynamic_range(peak, rms)

        # Create metrics object
        metrics = AudioMetrics(
            timestamp=datetime.utcnow(),
            rms_level=rms,
            peak_level=peak,
            noise_floor=noise_floor,
            snr=snr,
            clipping_detected=clipping,
            zero_crossing_rate=zcr,
            dynamic_range=dynamic_range
        )

        # Update session statistics
        self._update_session_stats(metrics)

        # Check for quality issues
        self._check_quality_thresholds(metrics, source)

        return metrics

    def _bytes_to_normalized_samples(self, audio_bytes: bytes) -> np.ndarray:
        """Convert PCM16 bytes to normalized float samples (-1.0 to 1.0)."""
        try:
            # Unpack 16-bit samples
            num_samples = len(audio_bytes) // 2
            samples = struct.unpack(f"<{num_samples}h", audio_bytes)

            # Normalize to -1.0 to 1.0
            normalized = np.array(samples, dtype=np.float32) / self.MAX_AMPLITUDE

            return normalized
        except Exception as e:
            logger.error(f"Error converting audio bytes: {e}")
            return np.array([])

    def _calculate_rms(self, samples: np.ndarray) -> float:
        """Calculate Root Mean Square (loudness measure)."""
        return float(np.sqrt(np.mean(samples ** 2)))

    def _calculate_peak(self, samples: np.ndarray) -> float:
        """Calculate peak amplitude."""
        return float(np.max(np.abs(samples)))

    def _estimate_noise_floor(self, samples: np.ndarray) -> float:
        """
        Estimate background noise level.
        Uses rolling percentile of low-energy regions.
        """
        # Use 10th percentile as noise floor estimate
        noise_estimate = float(np.percentile(np.abs(samples), 10))

        # Update rolling window
        self._noise_window.append(noise_estimate)
        if len(self._noise_window) > self._noise_window_size:
            self._noise_window.pop(0)

        # Return median of window for stability
        return float(np.median(self._noise_window)) if self._noise_window else noise_estimate

    def _calculate_snr(self, signal_rms: float, noise_floor: float) -> float:
        """
        Calculate Signal-to-Noise Ratio in dB.
        Higher is better (>30 dB = good, <20 dB = problematic).
        """
        if noise_floor <= 0 or signal_rms <= 0:
            return 0.0

        snr_db = 20 * np.log10(signal_rms / noise_floor)
        return float(snr_db)

    def _detect_clipping(self, samples: np.ndarray) -> bool:
        """
        Detect if audio is clipping (distortion).
        Returns True if any samples exceed threshold.
        """
        max_sample = np.max(np.abs(samples))
        return max_sample >= self.CLIPPING_THRESHOLD

    def _calculate_zero_crossing_rate(self, samples: np.ndarray) -> float:
        """
        Calculate zero-crossing rate (measure of frequency content).
        Low ZCR = low frequency, High ZCR = high frequency/noise.
        """
        zero_crossings = np.sum(np.abs(np.diff(np.sign(samples)))) / 2
        zcr = zero_crossings / len(samples)
        return float(zcr)

    def _calculate_dynamic_range(self, peak: float, rms: float) -> float:
        """
        Calculate dynamic range in dB.
        Low dynamic range suggests AGC is flattening the audio.
        """
        if rms <= 0 or peak <= 0:
            return 0.0

        dr_db = 20 * np.log10(peak / rms)
        return float(dr_db)

    def _update_session_stats(self, metrics: AudioMetrics):
        """Update running statistics for the session."""
        n = self.session.chunk_count

        # Running average
        self.session.avg_rms = (self.session.avg_rms * n + metrics.rms_level) / (n + 1)
        self.session.avg_snr = (self.session.avg_snr * n + metrics.snr) / (n + 1)
        self.session.avg_dynamic_range = (self.session.avg_dynamic_range * n + metrics.dynamic_range) / (n + 1)

        self.session.chunk_count += 1

        # Store in history (limit to last 100 chunks to avoid memory issues)
        if len(self.session.metrics_history) >= 100:
            self.session.metrics_history.pop(0)
        self.session.metrics_history.append(metrics)

    def _check_quality_thresholds(self, metrics: AudioMetrics, source: str):
        """Check if metrics exceed quality thresholds and log warnings."""
        issues = []

        # Check clipping
        if metrics.clipping_detected:
            self.session.clipping_events += 1
            issues.append(f"⚠️ Audio clipping detected in {source} stream")
            logger.warning(f"🔊 CLIPPING: {source} audio peak={metrics.peak_level:.3f}")

        # Check SNR
        if metrics.snr < self.MIN_SNR_DB:
            self.session.low_snr_events += 1
            issues.append(f"Low SNR ({metrics.snr:.1f} dB) in {source} stream")
            logger.warning(f"📉 LOW SNR: {source} audio SNR={metrics.snr:.1f} dB (threshold: {self.MIN_SNR_DB} dB)")

        # Check levels
        if metrics.rms_level < self.MIN_RMS_LEVEL:
            self.session.level_warnings += 1
            issues.append(f"{source} audio too quiet (RMS={metrics.rms_level:.3f})")
            logger.warning(f"🔉 QUIET AUDIO: {source} RMS={metrics.rms_level:.3f}")
        elif metrics.rms_level > self.MAX_RMS_LEVEL:
            self.session.level_warnings += 1
            issues.append(f"{source} audio too loud (RMS={metrics.rms_level:.3f})")
            logger.warning(f"🔊 LOUD AUDIO: {source} RMS={metrics.rms_level:.3f}")

        # Check dynamic range (AGC issues)
        if metrics.dynamic_range < 3.0:  # Less than 3 dB suggests heavy compression
            issues.append(f"Low dynamic range ({metrics.dynamic_range:.1f} dB) - possible AGC issue")
            logger.warning(f"📊 LOW DYNAMIC RANGE: {source} DR={metrics.dynamic_range:.1f} dB (AGC too aggressive?)")

        # Update session flags
        if issues:
            self.session.has_quality_issues = True
            self.session.issue_summary.extend(issues)

    def estimate_mos(self) -> float:
        """
        Estimate MOS (Mean Opinion Score) based on audio metrics.

        MOS Scale:
        5.0 = Excellent
        4.0 = Good
        3.0 = Fair
        2.0 = Poor
        1.0 = Bad

        This is a simplified heuristic. For true MOS, use POLQA/PESQ.
        """
        if self.session.chunk_count == 0:
            return 0.0

        # Start with perfect score
        mos = 5.0

        # Penalize based on issues

        # SNR impact (most important for quality)
        avg_snr = self.session.avg_snr
        if avg_snr < 10:
            mos -= 2.0  # Severe degradation
        elif avg_snr < 20:
            mos -= 1.0  # Noticeable degradation
        elif avg_snr < 30:
            mos -= 0.3  # Slight degradation

        # Clipping impact
        clipping_rate = self.session.clipping_events / self.session.chunk_count
        if clipping_rate > 0.1:  # More than 10% chunks clipping
            mos -= 1.5
        elif clipping_rate > 0.05:
            mos -= 0.7
        elif clipping_rate > 0.01:
            mos -= 0.3

        # Level consistency impact
        level_issue_rate = self.session.level_warnings / self.session.chunk_count
        if level_issue_rate > 0.2:
            mos -= 0.5

        # Dynamic range impact (AGC issues)
        if self.session.avg_dynamic_range < 3.0:
            mos -= 0.8  # Heavy compression = "PA system" sound
        elif self.session.avg_dynamic_range < 6.0:
            mos -= 0.3

        # Clamp to valid range
        mos = max(1.0, min(5.0, mos))

        self.session.estimated_mos = mos
        return mos

    def get_quality_summary(self) -> Dict:
        """
        Get comprehensive quality summary for logging/alerting.

        Returns dict compatible with Azure Log Analytics structured logging.
        """
        mos = self.estimate_mos()

        quality_rating = "EXCELLENT"
        if mos < 2.0:
            quality_rating = "BAD"
        elif mos < 3.0:
            quality_rating = "POOR"
        elif mos < 4.0:
            quality_rating = "FAIR"
        elif mos < 4.5:
            quality_rating = "GOOD"

        return {
            "session_id": self.session.session_id,
            "start_time": self.session.start_time.isoformat(),
            "duration_seconds": (datetime.utcnow() - self.session.start_time).total_seconds(),
            "chunk_count": self.session.chunk_count,

            # Quality scores
            "estimated_mos": round(mos, 2),
            "quality_rating": quality_rating,

            # Average metrics
            "avg_rms_level": round(self.session.avg_rms, 3),
            "avg_snr_db": round(self.session.avg_snr, 1),
            "avg_dynamic_range_db": round(self.session.avg_dynamic_range, 1),

            # Issue counts
            "clipping_events": self.session.clipping_events,
            "low_snr_events": self.session.low_snr_events,
            "level_warnings": self.session.level_warnings,

            # Flags
            "has_quality_issues": self.session.has_quality_issues,
            "issue_summary": self.session.issue_summary,

            # Compliance with guide thresholds
            "meets_snr_threshold": self.session.avg_snr >= self.MIN_SNR_DB,
            "has_clipping": self.session.clipping_events > 0,
            "agc_issues_detected": self.session.avg_dynamic_range < 6.0
        }

    def log_final_summary(self):
        """Log final quality summary at end of call."""
        summary = self.get_quality_summary()

        logger.info(f"📊 AUDIO QUALITY SUMMARY - Session {self.session.session_id}")
        logger.info(f"   MOS Score: {summary['estimated_mos']}/5.0 ({summary['quality_rating']})")
        logger.info(f"   Avg SNR: {summary['avg_snr_db']} dB")
        logger.info(f"   Avg Dynamic Range: {summary['avg_dynamic_range_db']} dB")
        logger.info(f"   Clipping Events: {summary['clipping_events']}")
        logger.info(f"   Low SNR Events: {summary['low_snr_events']}")

        if summary['has_quality_issues']:
            logger.warning(f"⚠️ Quality issues detected: {len(summary['issue_summary'])} issues")
            for issue in summary['issue_summary'][:5]:  # Show first 5
                logger.warning(f"   - {issue}")
        else:
            logger.info("✅ No significant quality issues detected")
