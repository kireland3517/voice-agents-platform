"""
Network Diagnostics Layer
Estimates network quality metrics (jitter, packet loss, RTT) for WebSocket-based voice calls.

Based on Azure S2S Voice Agent Quality Guide thresholds:
- Jitter > 30ms = problematic
- Packet loss > 10% = severe degradation
- RTT > 500ms = turn-taking issues

Since we're on WebSocket (not direct RTP/UDP), we infer quality issues from:
- Audio chunk timing irregularities → jitter estimation
- Missing/delayed frames → packet loss indicators
- Round-trip latency measurement between events
"""

import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

logger = logging.getLogger("network_diagnostics")


@dataclass
class NetworkMetrics:
    """Network quality metrics for a time window."""
    timestamp: datetime
    jitter_avg_ms: float  # Average jitter in milliseconds
    jitter_max_ms: float  # Peak jitter
    packet_loss_rate: float  # Estimated packet loss (0.0 - 1.0)
    round_trip_time_ms: float  # RTT in milliseconds
    frame_timing_variance: float  # Variance in frame arrival times


@dataclass
class NetworkSession:
    """Aggregate network diagnostics for a call session."""
    session_id: str
    start_time: datetime

    # Running averages
    avg_jitter_ms: float = 0.0
    avg_rtt_ms: float = 0.0
    avg_packet_loss_rate: float = 0.0

    # Quality events
    jitter_warnings: int = 0  # Jitter > 30ms
    packet_loss_warnings: int = 0  # Loss > 10%
    rtt_warnings: int = 0  # RTT > 500ms

    # Sample count
    sample_count: int = 0

    # History
    metrics_history: List[NetworkMetrics] = field(default_factory=list)

    # Flags
    has_network_issues: bool = False
    issue_summary: List[str] = field(default_factory=list)


class NetworkDiagnostics:
    """
    Monitors network quality for WebSocket-based voice calls.

    Estimates jitter, packet loss, and RTT based on audio chunk arrival patterns.
    """

    # Thresholds from Azure guide
    JITTER_WARNING_MS = 30.0  # > 30ms = robotic audio
    PACKET_LOSS_WARNING = 0.10  # > 10% = severe degradation
    RTT_WARNING_MS = 500.0  # > 500ms = turn-taking issues

    # Expected audio chunk interval (100ms for 2400 samples @ 24kHz)
    EXPECTED_CHUNK_INTERVAL_MS = 100.0

    def __init__(self, session_id: str):
        """Initialize network diagnostics for a call session."""
        self.session = NetworkSession(
            session_id=session_id,
            start_time=datetime.utcnow()
        )

        # Frame arrival timing tracking
        self._chunk_arrival_times: deque = deque(maxlen=50)  # Last 50 chunks
        self._expected_chunks = 0
        self._received_chunks = 0

        # RTT measurement
        self._ping_sent_time = None
        self._rtt_samples: deque = deque(maxlen=20)

        logger.info(f"🌐 NetworkDiagnostics initialized for session {session_id}")

    def record_chunk_arrival(self, chunk_size: int):
        """
        Record the arrival of an audio chunk.

        Args:
            chunk_size: Size of chunk in bytes (for validation)
        """
        arrival_time = time.perf_counter()
        self._chunk_arrival_times.append(arrival_time)
        self._received_chunks += 1

        # Calculate expected chunks based on time elapsed
        if len(self._chunk_arrival_times) >= 2:
            time_elapsed_s = self._chunk_arrival_times[-1] - self._chunk_arrival_times[0]
            self._expected_chunks = int(time_elapsed_s * 1000 / self.EXPECTED_CHUNK_INTERVAL_MS)

    def calculate_jitter(self) -> tuple[float, float]:
        """
        Calculate jitter (variation in packet arrival times).

        Returns:
            (avg_jitter_ms, max_jitter_ms)
        """
        if len(self._chunk_arrival_times) < 3:
            return (0.0, 0.0)

        # Calculate inter-arrival times
        inter_arrival_times = []
        for i in range(1, len(self._chunk_arrival_times)):
            delta_ms = (self._chunk_arrival_times[i] - self._chunk_arrival_times[i-1]) * 1000
            inter_arrival_times.append(delta_ms)

        # Jitter is the variance from expected interval
        jitter_samples = []
        for delta_ms in inter_arrival_times:
            jitter = abs(delta_ms - self.EXPECTED_CHUNK_INTERVAL_MS)
            jitter_samples.append(jitter)

        if not jitter_samples:
            return (0.0, 0.0)

        avg_jitter = sum(jitter_samples) / len(jitter_samples)
        max_jitter = max(jitter_samples)

        return (avg_jitter, max_jitter)

    def estimate_packet_loss(self) -> float:
        """
        Estimate packet loss rate based on missing chunks.

        Returns:
            Packet loss rate (0.0 - 1.0)
        """
        if self._expected_chunks == 0:
            return 0.0

        missing_chunks = max(0, self._expected_chunks - self._received_chunks)
        loss_rate = missing_chunks / self._expected_chunks

        # Clamp to realistic range
        return min(1.0, max(0.0, loss_rate))

    def record_ping(self):
        """Record that a ping/request was sent (for RTT measurement)."""
        self._ping_sent_time = time.perf_counter()

    def record_pong(self):
        """Record that a pong/response was received (complete RTT measurement)."""
        if self._ping_sent_time is None:
            return

        pong_time = time.perf_counter()
        rtt_ms = (pong_time - self._ping_sent_time) * 1000
        self._rtt_samples.append(rtt_ms)
        self._ping_sent_time = None

    def get_current_rtt(self) -> float:
        """
        Get current RTT estimate.

        Returns:
            RTT in milliseconds (or 0 if no samples)
        """
        if not self._rtt_samples:
            return 0.0

        # Use median for robustness
        sorted_samples = sorted(self._rtt_samples)
        mid = len(sorted_samples) // 2
        return sorted_samples[mid]

    def analyze_and_update(self):
        """
        Analyze current network conditions and update session metrics.
        Call this periodically (e.g., every 5-10 seconds).
        """
        # Calculate current metrics
        avg_jitter, max_jitter = self.calculate_jitter()
        packet_loss = self.estimate_packet_loss()
        rtt = self.get_current_rtt()

        # Calculate frame timing variance
        if len(self._chunk_arrival_times) >= 2:
            inter_arrivals = []
            for i in range(1, len(self._chunk_arrival_times)):
                delta = (self._chunk_arrival_times[i] - self._chunk_arrival_times[i-1]) * 1000
                inter_arrivals.append(delta)

            if inter_arrivals:
                mean = sum(inter_arrivals) / len(inter_arrivals)
                variance = sum((x - mean) ** 2 for x in inter_arrivals) / len(inter_arrivals)
            else:
                variance = 0.0
        else:
            variance = 0.0

        # Create metrics snapshot
        metrics = NetworkMetrics(
            timestamp=datetime.utcnow(),
            jitter_avg_ms=avg_jitter,
            jitter_max_ms=max_jitter,
            packet_loss_rate=packet_loss,
            round_trip_time_ms=rtt,
            frame_timing_variance=variance
        )

        # Update session statistics
        self._update_session_stats(metrics)

        # Check thresholds and log warnings
        self._check_thresholds(metrics)

        return metrics

    def _update_session_stats(self, metrics: NetworkMetrics):
        """Update running statistics for the session."""
        n = self.session.sample_count

        # Running averages
        self.session.avg_jitter_ms = (self.session.avg_jitter_ms * n + metrics.jitter_avg_ms) / (n + 1)
        self.session.avg_rtt_ms = (self.session.avg_rtt_ms * n + metrics.round_trip_time_ms) / (n + 1)
        self.session.avg_packet_loss_rate = (self.session.avg_packet_loss_rate * n + metrics.packet_loss_rate) / (n + 1)

        self.session.sample_count += 1

        # Store in history (limit to last 50 samples)
        if len(self.session.metrics_history) >= 50:
            self.session.metrics_history.pop(0)
        self.session.metrics_history.append(metrics)

    def _check_thresholds(self, metrics: NetworkMetrics):
        """Check if metrics exceed Azure guide thresholds and log warnings."""
        issues = []

        # Check jitter (> 30ms = robotic/metallic audio)
        if metrics.jitter_avg_ms > self.JITTER_WARNING_MS:
            self.session.jitter_warnings += 1
            self.session.has_network_issues = True
            issues.append(f"High jitter: {metrics.jitter_avg_ms:.1f}ms (threshold: {self.JITTER_WARNING_MS}ms)")
            logger.warning(
                f"🌊 HIGH JITTER: {metrics.jitter_avg_ms:.1f}ms avg, {metrics.jitter_max_ms:.1f}ms peak "
                f"(threshold: {self.JITTER_WARNING_MS}ms) - EXPECT ROBOTIC/METALLIC AUDIO"
            )

        # Check packet loss (> 10% = severe degradation)
        if metrics.packet_loss_rate > self.PACKET_LOSS_WARNING:
            self.session.packet_loss_warnings += 1
            self.session.has_network_issues = True
            issues.append(f"Packet loss: {metrics.packet_loss_rate*100:.1f}% (threshold: {self.PACKET_LOSS_WARNING*100:.0f}%)")
            logger.warning(
                f"📉 HIGH PACKET LOSS: {metrics.packet_loss_rate*100:.1f}% "
                f"(threshold: {self.PACKET_LOSS_WARNING*100:.0f}%) - EXPECT DROPOUTS/GURGLING"
            )

        # Check RTT (> 500ms = turn-taking issues)
        if metrics.round_trip_time_ms > self.RTT_WARNING_MS:
            self.session.rtt_warnings += 1
            self.session.has_network_issues = True
            issues.append(f"High RTT: {metrics.round_trip_time_ms:.0f}ms (threshold: {self.RTT_WARNING_MS:.0f}ms)")
            logger.warning(
                f"🐌 HIGH RTT: {metrics.round_trip_time_ms:.0f}ms "
                f"(threshold: {self.RTT_WARNING_MS:.0f}ms) - EXPECT OVERLAPPING SPEECH/DELAYS"
            )

        if issues:
            self.session.issue_summary.extend(issues)

    def get_diagnostics_summary(self) -> Dict:
        """
        Get comprehensive network diagnostics summary.

        Returns dict compatible with Azure Log Analytics structured logging.
        """
        # Determine network quality rating
        network_quality = "EXCELLENT"
        if (self.session.avg_jitter_ms > self.JITTER_WARNING_MS or
            self.session.avg_packet_loss_rate > self.PACKET_LOSS_WARNING or
            self.session.avg_rtt_ms > self.RTT_WARNING_MS):
            network_quality = "POOR"
        elif (self.session.avg_jitter_ms > self.JITTER_WARNING_MS * 0.7 or
              self.session.avg_packet_loss_rate > self.PACKET_LOSS_WARNING * 0.7 or
              self.session.avg_rtt_ms > self.RTT_WARNING_MS * 0.7):
            network_quality = "FAIR"
        elif (self.session.avg_jitter_ms > self.JITTER_WARNING_MS * 0.4 or
              self.session.avg_packet_loss_rate > self.PACKET_LOSS_WARNING * 0.4 or
              self.session.avg_rtt_ms > self.RTT_WARNING_MS * 0.4):
            network_quality = "GOOD"

        return {
            "session_id": self.session.session_id,
            "start_time": self.session.start_time.isoformat(),
            "duration_seconds": (datetime.utcnow() - self.session.start_time).total_seconds(),
            "sample_count": self.session.sample_count,

            # Quality rating
            "network_quality": network_quality,

            # Average metrics
            "avg_jitter_ms": round(self.session.avg_jitter_ms, 2),
            "avg_packet_loss_pct": round(self.session.avg_packet_loss_rate * 100, 2),
            "avg_rtt_ms": round(self.session.avg_rtt_ms, 1),

            # Warning counts
            "jitter_warnings": self.session.jitter_warnings,
            "packet_loss_warnings": self.session.packet_loss_warnings,
            "rtt_warnings": self.session.rtt_warnings,

            # Flags
            "has_network_issues": self.session.has_network_issues,
            "issue_summary": self.session.issue_summary,

            # Compliance with Azure guide thresholds
            "exceeds_jitter_threshold": self.session.avg_jitter_ms > self.JITTER_WARNING_MS,
            "exceeds_packet_loss_threshold": self.session.avg_packet_loss_rate > self.PACKET_LOSS_WARNING,
            "exceeds_rtt_threshold": self.session.avg_rtt_ms > self.RTT_WARNING_MS,

            # Additional context
            "chunks_received": self._received_chunks,
            "chunks_expected": self._expected_chunks
        }

    def log_final_summary(self):
        """Log final network diagnostics summary at end of call."""
        summary = self.get_diagnostics_summary()

        logger.info(f"🌐 NETWORK DIAGNOSTICS SUMMARY - Session {self.session.session_id}")
        logger.info(f"   Network Quality: {summary['network_quality']}")
        logger.info(f"   Avg Jitter: {summary['avg_jitter_ms']:.1f}ms (threshold: {self.JITTER_WARNING_MS}ms)")
        logger.info(f"   Avg Packet Loss: {summary['avg_packet_loss_pct']:.1f}% (threshold: {self.PACKET_LOSS_WARNING*100:.0f}%)")
        logger.info(f"   Avg RTT: {summary['avg_rtt_ms']:.0f}ms (threshold: {self.RTT_WARNING_MS:.0f}ms)")
        logger.info(f"   Chunks: {summary['chunks_received']}/{summary['chunks_expected']} received")

        if summary['has_network_issues']:
            logger.warning(f"⚠️ Network issues detected:")
            logger.warning(f"   Jitter warnings: {summary['jitter_warnings']}")
            logger.warning(f"   Packet loss warnings: {summary['packet_loss_warnings']}")
            logger.warning(f"   RTT warnings: {summary['rtt_warnings']}")
            logger.warning("   → This WILL cause robotic/metallic audio quality")
        else:
            logger.info("✅ No significant network issues detected")

    def should_alert(self) -> tuple[bool, str]:
        """
        Determine if an alert should be raised based on current network conditions.

        Returns:
            (should_alert, reason)
        """
        if self.session.sample_count == 0:
            return (False, "")

        # Alert if any threshold exceeded
        if self.session.avg_jitter_ms > self.JITTER_WARNING_MS:
            return (True, f"Jitter {self.session.avg_jitter_ms:.1f}ms > {self.JITTER_WARNING_MS}ms")

        if self.session.avg_packet_loss_rate > self.PACKET_LOSS_WARNING:
            return (True, f"Packet loss {self.session.avg_packet_loss_rate*100:.1f}% > {self.PACKET_LOSS_WARNING*100:.0f}%")

        if self.session.avg_rtt_ms > self.RTT_WARNING_MS:
            return (True, f"RTT {self.session.avg_rtt_ms:.0f}ms > {self.RTT_WARNING_MS:.0f}ms")

        return (False, "")
