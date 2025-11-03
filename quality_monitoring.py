"""
Quality Monitoring Integration
Unified interface for all quality monitoring components.

Based on Azure S2S Voice Agent Quality Guide.
Integrates: AudioQualityMonitor, NetworkDiagnostics, CallDiagnosticsLogger, MOSScorer
"""

import logging
import asyncio
from typing import Optional, Dict
from datetime import datetime

from audio_quality_monitor import AudioQualityMonitor
from network_diagnostics import NetworkDiagnostics
from call_diagnostics_logger import CallDiagnosticsLogger
from mos_scorer import MOSScorer

logger = logging.getLogger("quality_monitoring")


class QualityMonitoringSession:
    """
    Unified quality monitoring for a single call session.

    Orchestrates all quality monitoring components:
    - Audio quality analysis
    - Network diagnostics
    - Turn-timing analysis
    - MOS scoring
    - Structured logging for Azure Log Analytics
    """

    def __init__(self,
                 call_id: str,
                 company_id: str,
                 config: Dict):
        """
        Initialize quality monitoring for a call.

        Args:
            call_id: Unique call identifier
            company_id: Company identifier
            config: Audio settings dict with quality monitoring config
        """
        self.call_id = call_id
        self.company_id = company_id
        self.config = config
        self.start_time = datetime.utcnow()

        # Extract quality monitoring configuration
        self.enabled = config.get('enable-audio-quality-monitoring', True)
        self.network_enabled = config.get('enable-network-diagnostics', True)
        self.mos_enabled = config.get('enable-mos-scoring', False)
        self.structured_logging_enabled = config.get('enable-structured-diagnostics-logging', True)

        # Initialize components
        self.audio_monitor: Optional[AudioQualityMonitor] = None
        self.network_diagnostics: Optional[NetworkDiagnostics] = None
        self.diagnostics_logger: Optional[CallDiagnosticsLogger] = None
        self.mos_scorer: Optional[MOSScorer] = None

        # Periodic analysis tasks
        self._audio_analysis_task = None
        self._network_analysis_task = None

        # Initialize if enabled
        if self.enabled:
            self._initialize_components()

    def _initialize_components(self):
        """Initialize quality monitoring components based on configuration."""
        try:
            # Audio quality monitor
            self.audio_monitor = AudioQualityMonitor(session_id=self.call_id)
            logger.info(f"✅ Audio quality monitoring initialized for call {self.call_id}")

            # Network diagnostics
            if self.network_enabled:
                self.network_diagnostics = NetworkDiagnostics(session_id=self.call_id)
                logger.info(f"✅ Network diagnostics initialized for call {self.call_id}")

            # Structured logging
            if self.structured_logging_enabled:
                self.diagnostics_logger = CallDiagnosticsLogger(
                    call_id=self.call_id,
                    company_id=self.company_id
                )
                self.diagnostics_logger.log_call_start({
                    "audio_quality_monitoring": self.enabled,
                    "network_diagnostics": self.network_enabled,
                    "mos_scoring": self.mos_enabled
                })
                logger.info(f"✅ Structured diagnostics logging initialized for call {self.call_id}")

            # MOS scorer (optional, requires PESQ)
            if self.mos_enabled:
                self.mos_scorer = MOSScorer()
                if not self.mos_scorer.is_pesq_available():
                    logger.warning("⚠️ MOS scoring enabled but PESQ not available")
                    logger.warning(self.mos_scorer.get_installation_instructions())
                    self.mos_enabled = False
                else:
                    logger.info(f"✅ MOS scoring initialized for call {self.call_id}")

        except Exception as e:
            logger.error(f"❌ Error initializing quality monitoring: {e}")
            self.enabled = False

    async def start_periodic_analysis(self):
        """Start background tasks for periodic quality analysis."""
        if not self.enabled:
            return

        # Audio quality analysis interval
        audio_interval = self.config.get('quality-analysis-interval-seconds', 10)
        network_interval = self.config.get('network-analysis-interval-seconds', 5)

        # Start audio analysis task
        self._audio_analysis_task = asyncio.create_task(
            self._periodic_audio_analysis(audio_interval)
        )

        # Start network analysis task
        if self.network_enabled and self.network_diagnostics:
            self._network_analysis_task = asyncio.create_task(
                self._periodic_network_analysis(network_interval)
            )

        logger.info(f"🔄 Started periodic quality analysis (audio: {audio_interval}s, network: {network_interval}s)")

    async def _periodic_audio_analysis(self, interval: int):
        """Periodically analyze audio quality and log metrics."""
        try:
            while True:
                await asyncio.sleep(interval)

                if self.audio_monitor:
                    mos = self.audio_monitor.estimate_mos()

                    # Log to structured logger if enabled
                    if self.diagnostics_logger and self.audio_monitor.session.chunk_count > 0:
                        self.diagnostics_logger.log_audio_quality_metrics(
                            mos=mos,
                            snr_db=self.audio_monitor.session.avg_snr,
                            dynamic_range_db=self.audio_monitor.session.avg_dynamic_range,
                            clipping_detected=self.audio_monitor.session.clipping_events > 0
                        )

        except asyncio.CancelledError:
            logger.debug("Audio analysis task cancelled")
        except Exception as e:
            logger.error(f"Error in periodic audio analysis: {e}")

    async def _periodic_network_analysis(self, interval: int):
        """Periodically analyze network quality and log metrics."""
        try:
            while True:
                await asyncio.sleep(interval)

                if self.network_diagnostics:
                    # Analyze current network conditions
                    metrics = self.network_diagnostics.analyze_and_update()

                    # Log to structured logger if enabled
                    if self.diagnostics_logger and metrics:
                        self.diagnostics_logger.log_network_metrics(
                            jitter_ms=metrics.jitter_avg_ms,
                            packet_loss_rate=metrics.packet_loss_rate,
                            rtt_ms=metrics.round_trip_time_ms
                        )

                    # Check if alert should be raised
                    should_alert, reason = self.network_diagnostics.should_alert()
                    if should_alert:
                        logger.warning(f"🚨 NETWORK QUALITY ALERT: {reason}")

        except asyncio.CancelledError:
            logger.debug("Network analysis task cancelled")
        except Exception as e:
            logger.error(f"Error in periodic network analysis: {e}")

    def analyze_audio_chunk(self, audio_bytes: bytes, source: str = "ai"):
        """
        Analyze a single audio chunk for quality.

        Args:
            audio_bytes: PCM16 audio data
            source: "ai" or "caller"
        """
        if not self.enabled or not self.audio_monitor:
            return

        try:
            self.audio_monitor.analyze_chunk(audio_bytes, source=source)
        except Exception as e:
            logger.error(f"Error analyzing audio chunk: {e}")

    def record_audio_chunk_arrival(self, chunk_size: int):
        """
        Record the arrival of an audio chunk for network diagnostics.

        Args:
            chunk_size: Size of chunk in bytes
        """
        if not self.network_enabled or not self.network_diagnostics:
            return

        try:
            self.network_diagnostics.record_chunk_arrival(chunk_size)
        except Exception as e:
            logger.error(f"Error recording chunk arrival: {e}")

    def log_turn_timing(self, response_gap_ms: float):
        """
        Log turn-timing metrics.

        Args:
            response_gap_ms: Gap between caller stop and AI start in milliseconds
        """
        if not self.structured_logging_enabled or not self.diagnostics_logger:
            return

        try:
            self.diagnostics_logger.log_turn_timing(response_gap_ms)
        except Exception as e:
            logger.error(f"Error logging turn timing: {e}")

    def calculate_mos(self, reference_audio: bytes, degraded_audio: bytes) -> Optional[float]:
        """
        Calculate MOS score comparing reference vs degraded audio.

        Args:
            reference_audio: Clean TTS output
            degraded_audio: Audio as received

        Returns:
            MOS score (1.0-5.0) or None if MOS scoring disabled
        """
        if not self.mos_enabled or not self.mos_scorer:
            return None

        try:
            sample_rate = self.config.get('audio-sample-rate', 24000)
            mos = self.mos_scorer.calculate_mos(
                reference_audio=reference_audio,
                degraded_audio=degraded_audio,
                sample_rate=sample_rate,
                mode="wb"
            )
            return mos
        except Exception as e:
            logger.error(f"Error calculating MOS: {e}")
            return None

    async def finalize(self, session_monitor):
        """
        Finalize quality monitoring at end of call.

        Args:
            session_monitor: SessionMonitor instance with call statistics
        """
        try:
            # Cancel periodic tasks
            if self._audio_analysis_task:
                self._audio_analysis_task.cancel()
                try:
                    await self._audio_analysis_task
                except asyncio.CancelledError:
                    pass

            if self._network_analysis_task:
                self._network_analysis_task.cancel()
                try:
                    await self._network_analysis_task
                except asyncio.CancelledError:
                    pass

            # Log final summaries
            if self.audio_monitor:
                self.audio_monitor.log_final_summary()

            if self.network_diagnostics:
                self.network_diagnostics.log_final_summary()

            # Log structured call end event
            if self.diagnostics_logger and self.audio_monitor and self.network_diagnostics:
                duration = (datetime.utcnow() - self.start_time).total_seconds()

                # Get latency stats
                latency_stats = session_monitor.get_latency_stats()
                natural_rate = 0.0
                avg_gap = 0.0

                if latency_stats:
                    total_responses = latency_stats['count']
                    natural_responses = latency_stats['natural_responses']
                    natural_rate = natural_responses / total_responses if total_responses > 0 else 0.0
                    avg_gap = latency_stats['avg_ms']

                # Build session summary
                session_summary = {
                    'turn_count': session_monitor.turn_count,
                    'token_count': session_monitor.token_count,
                    'vad_triggers': session_monitor.vad_triggers,
                    'function_calls': len(session_monitor.function_calls),
                    'errors': len(session_monitor.errors),
                    'avg_response_gap_ms': avg_gap,
                    'natural_response_rate': natural_rate
                }

                self.diagnostics_logger.log_call_end(
                    duration_seconds=duration,
                    audio_quality_summary=self.audio_monitor.get_quality_summary(),
                    network_summary=self.network_diagnostics.get_diagnostics_summary(),
                    session_summary=session_summary
                )

            logger.info(f"✅ Quality monitoring finalized for call {self.call_id}")

        except Exception as e:
            logger.error(f"Error finalizing quality monitoring: {e}")

    def get_summary(self) -> Dict:
        """
        Get comprehensive quality monitoring summary.

        Returns:
            Dict with all quality metrics
        """
        summary = {
            "call_id": self.call_id,
            "company_id": self.company_id,
            "monitoring_enabled": self.enabled
        }

        if self.audio_monitor:
            summary["audio_quality"] = self.audio_monitor.get_quality_summary()

        if self.network_diagnostics:
            summary["network"] = self.network_diagnostics.get_diagnostics_summary()

        return summary
