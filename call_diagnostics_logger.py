"""
Call Diagnostics Logger
Structured logging for Azure Log Analytics integration.

Produces JSON-formatted diagnostic events compatible with Azure Monitor/Log Analytics.
Based on Azure S2S Voice Agent Quality Guide recommendations.
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger("call_diagnostics")


class DiagnosticEventType(Enum):
    """Types of diagnostic events."""
    CALL_START = "call_start"
    CALL_END = "call_end"
    QUALITY_WARNING = "quality_warning"
    QUALITY_ALERT = "quality_alert"
    NETWORK_DEGRADATION = "network_degradation"
    AUDIO_QUALITY_ISSUE = "audio_quality_issue"
    TURN_TIMING_ISSUE = "turn_timing_issue"
    VAD_EVENT = "vad_event"
    PERIODIC_METRICS = "periodic_metrics"


class CallDiagnosticsLogger:
    """
    Structured logger for call quality diagnostics.

    Produces JSON events that can be ingested by Azure Log Analytics
    for querying and alerting (as per guide's Kusto query examples).
    """

    def __init__(self, call_id: str, company_id: str):
        """
        Initialize diagnostics logger for a call.

        Args:
            call_id: Unique call identifier (e.g., SignalWire call SID)
            company_id: Company identifier
        """
        self.call_id = call_id
        self.company_id = company_id
        self.call_start_time = datetime.utcnow()

        # Diagnostic event sequence
        self.event_sequence = 0

    def _create_base_event(self, event_type: DiagnosticEventType) -> Dict[str, Any]:
        """Create base diagnostic event structure."""
        self.event_sequence += 1

        return {
            # Event metadata
            "event_type": event_type.value,
            "event_sequence": self.event_sequence,
            "timestamp": datetime.utcnow().isoformat(),

            # Call context
            "call_id": self.call_id,
            "company_id": self.company_id,
            "call_start_time": self.call_start_time.isoformat(),

            # Placeholder for event-specific data
            "data": {}
        }

    def log_call_start(self, metadata: Optional[Dict] = None):
        """Log call start event."""
        event = self._create_base_event(DiagnosticEventType.CALL_START)
        event["data"] = metadata or {}

        self._emit_structured_log(event, level=logging.INFO)

    def log_call_end(self,
                     duration_seconds: float,
                     audio_quality_summary: Dict,
                     network_summary: Dict,
                     session_summary: Dict):
        """
        Log call end event with comprehensive quality summary.

        Args:
            duration_seconds: Total call duration
            audio_quality_summary: From AudioQualityMonitor.get_quality_summary()
            network_summary: From NetworkDiagnostics.get_diagnostics_summary()
            session_summary: Session metrics (tokens, turns, etc.)
        """
        event = self._create_base_event(DiagnosticEventType.CALL_END)

        event["data"] = {
            "duration_seconds": round(duration_seconds, 1),

            # Audio quality metrics (compatible with guide's MOS scoring)
            "audio_quality": {
                "estimated_mos": audio_quality_summary.get("estimated_mos", 0.0),
                "quality_rating": audio_quality_summary.get("quality_rating", "UNKNOWN"),
                "avg_snr_db": audio_quality_summary.get("avg_snr_db", 0.0),
                "avg_dynamic_range_db": audio_quality_summary.get("avg_dynamic_range_db", 0.0),
                "clipping_events": audio_quality_summary.get("clipping_events", 0),
                "has_quality_issues": audio_quality_summary.get("has_quality_issues", False)
            },

            # Network metrics (compatible with guide's ACS diagnostics schema)
            "network": {
                "network_quality": network_summary.get("network_quality", "UNKNOWN"),
                "jitter_avg_ms": network_summary.get("avg_jitter_ms", 0.0),
                "packet_loss_rate": network_summary.get("avg_packet_loss_pct", 0.0) / 100,  # Convert to 0.0-1.0
                "round_trip_time_ms": network_summary.get("avg_rtt_ms", 0.0),
                "exceeds_jitter_threshold": network_summary.get("exceeds_jitter_threshold", False),
                "exceeds_packet_loss_threshold": network_summary.get("exceeds_packet_loss_threshold", False),
                "exceeds_rtt_threshold": network_summary.get("exceeds_rtt_threshold", False)
            },

            # Session metrics
            "session": {
                "turn_count": session_summary.get("turn_count", 0),
                "token_count": session_summary.get("token_count", 0),
                "vad_triggers": session_summary.get("vad_triggers", 0),
                "function_calls": session_summary.get("function_calls", 0),
                "errors": session_summary.get("errors", 0),
                "avg_response_gap_ms": session_summary.get("avg_response_gap_ms", 0.0),
                "natural_response_rate": session_summary.get("natural_response_rate", 0.0)
            },

            # Overall quality assessment
            "overall_quality": self._assess_overall_quality(audio_quality_summary, network_summary, session_summary)
        }

        self._emit_structured_log(event, level=logging.INFO)

    def log_quality_warning(self,
                           category: str,
                           metric_name: str,
                           metric_value: float,
                           threshold: float,
                           description: str):
        """
        Log a quality warning event.

        Args:
            category: "audio", "network", or "timing"
            metric_name: Name of the metric that triggered warning
            metric_value: Current value
            threshold: Threshold that was exceeded
            description: Human-readable description
        """
        event = self._create_base_event(DiagnosticEventType.QUALITY_WARNING)

        event["data"] = {
            "category": category,
            "metric_name": metric_name,
            "metric_value": round(metric_value, 2),
            "threshold": round(threshold, 2),
            "description": description,
            "severity": "warning"
        }

        self._emit_structured_log(event, level=logging.WARNING)

    def log_quality_alert(self,
                         category: str,
                         metric_name: str,
                         metric_value: float,
                         threshold: float,
                         impact: str):
        """
        Log a critical quality alert event.

        Args:
            category: "audio", "network", or "timing"
            metric_name: Name of the metric that triggered alert
            metric_value: Current value
            threshold: Threshold that was exceeded
            impact: Expected impact on user experience
        """
        event = self._create_base_event(DiagnosticEventType.QUALITY_ALERT)

        event["data"] = {
            "category": category,
            "metric_name": metric_name,
            "metric_value": round(metric_value, 2),
            "threshold": round(threshold, 2),
            "impact": impact,
            "severity": "alert"
        }

        self._emit_structured_log(event, level=logging.ERROR)

    def log_network_metrics(self,
                           jitter_ms: float,
                           packet_loss_rate: float,
                           rtt_ms: float):
        """
        Log periodic network metrics snapshot.

        These are the key metrics from the Azure guide for detecting
        "robotic/metallic" audio quality.
        """
        event = self._create_base_event(DiagnosticEventType.PERIODIC_METRICS)

        event["data"] = {
            "metrics_type": "network",
            "jitter_avg_ms": round(jitter_ms, 2),
            "packet_loss_rate": round(packet_loss_rate, 4),
            "round_trip_time_ms": round(rtt_ms, 1)
        }

        # Check thresholds and upgrade to warning/alert if needed
        if jitter_ms > 30 or packet_loss_rate > 0.10 or rtt_ms > 500:
            self._emit_structured_log(event, level=logging.WARNING)

            # Emit specific alerts
            if jitter_ms > 30:
                self.log_quality_alert(
                    category="network",
                    metric_name="jitter_avg_ms",
                    metric_value=jitter_ms,
                    threshold=30.0,
                    impact="Robotic/metallic audio quality (Guide Section 1.1)"
                )

            if packet_loss_rate > 0.10:
                self.log_quality_alert(
                    category="network",
                    metric_name="packet_loss_rate",
                    metric_value=packet_loss_rate,
                    threshold=0.10,
                    impact="Dropouts, gurgling, underwater speech (Guide Section 1.1)"
                )

            if rtt_ms > 500:
                self.log_quality_alert(
                    category="network",
                    metric_name="round_trip_time_ms",
                    metric_value=rtt_ms,
                    threshold=500.0,
                    impact="Overlapping speech, awkward delays (Guide Section 1.1)"
                )
        else:
            self._emit_structured_log(event, level=logging.DEBUG)

    def log_audio_quality_metrics(self,
                                  mos: float,
                                  snr_db: float,
                                  dynamic_range_db: float,
                                  clipping_detected: bool):
        """
        Log periodic audio quality metrics snapshot.
        """
        event = self._create_base_event(DiagnosticEventType.PERIODIC_METRICS)

        event["data"] = {
            "metrics_type": "audio_quality",
            "estimated_mos": round(mos, 2),
            "snr_db": round(snr_db, 1),
            "dynamic_range_db": round(dynamic_range_db, 1),
            "clipping_detected": clipping_detected
        }

        # Check for issues
        has_issues = False

        if mos < 3.0:
            has_issues = True
            self.log_quality_warning(
                category="audio",
                metric_name="estimated_mos",
                metric_value=mos,
                threshold=3.0,
                description="Low MOS score indicates poor audio quality"
            )

        if snr_db < 20.0:
            has_issues = True
            self.log_quality_warning(
                category="audio",
                metric_name="snr_db",
                metric_value=snr_db,
                threshold=20.0,
                description="Low SNR - excessive noise"
            )

        if dynamic_range_db < 3.0:
            has_issues = True
            self.log_quality_warning(
                category="audio",
                metric_name="dynamic_range_db",
                metric_value=dynamic_range_db,
                threshold=3.0,
                description="Low dynamic range - possible AGC issue (Guide Section 1.3)"
            )

        if clipping_detected:
            has_issues = True
            self.log_quality_alert(
                category="audio",
                metric_name="clipping",
                metric_value=1.0,
                threshold=0.0,
                impact="Audio distortion detected"
            )

        level = logging.WARNING if has_issues else logging.DEBUG
        self._emit_structured_log(event, level=level)

    def log_turn_timing(self,
                       response_gap_ms: float):
        """
        Log turn-timing metrics.

        Guide recommendation: 200-500ms gap = natural conversation
        """
        event = self._create_base_event(DiagnosticEventType.PERIODIC_METRICS)

        event["data"] = {
            "metrics_type": "turn_timing",
            "response_gap_ms": round(response_gap_ms, 0)
        }

        # Check for timing issues
        if response_gap_ms < 100:
            self.log_quality_warning(
                category="timing",
                metric_name="response_gap_ms",
                metric_value=response_gap_ms,
                threshold=200.0,
                description="Instant response - sounds robotic (Guide Section 6.2)"
            )
            level = logging.WARNING
        elif response_gap_ms > 1500:
            self.log_quality_warning(
                category="timing",
                metric_name="response_gap_ms",
                metric_value=response_gap_ms,
                threshold=1500.0,
                description="Slow response - awkward delay (Guide Section 6.2)"
            )
            level = logging.WARNING
        elif 200 <= response_gap_ms <= 500:
            level = logging.DEBUG  # Natural timing, no warning needed
        else:
            level = logging.DEBUG

        self._emit_structured_log(event, level=level)

    def _assess_overall_quality(self,
                               audio_summary: Dict,
                               network_summary: Dict,
                               session_summary: Dict) -> Dict:
        """
        Assess overall call quality based on all metrics.

        Returns comprehensive quality assessment.
        """
        # Count issues
        issues = []

        # Audio issues
        if audio_summary.get("has_quality_issues", False):
            issues.append("audio_quality")

        mos = audio_summary.get("estimated_mos", 5.0)
        if mos < 3.0:
            issues.append("low_mos")

        # Network issues
        if network_summary.get("exceeds_jitter_threshold", False):
            issues.append("high_jitter")

        if network_summary.get("exceeds_packet_loss_threshold", False):
            issues.append("packet_loss")

        if network_summary.get("exceeds_rtt_threshold", False):
            issues.append("high_rtt")

        # Turn-timing issues
        natural_rate = session_summary.get("natural_response_rate", 1.0)
        if natural_rate < 0.5:  # Less than 50% natural timing
            issues.append("poor_turn_timing")

        # Overall rating
        if len(issues) == 0:
            overall_rating = "EXCELLENT"
            user_experience = "Natural, high-quality conversation"
        elif len(issues) == 1:
            overall_rating = "GOOD"
            user_experience = "Minor quality issues, generally acceptable"
        elif len(issues) <= 3:
            overall_rating = "FAIR"
            user_experience = "Noticeable quality issues"
        elif len(issues) <= 5:
            overall_rating = "POOR"
            user_experience = "Significant quality degradation"
        else:
            overall_rating = "BAD"
            user_experience = "Severe quality issues - robotic/metallic sound"

        # Root cause analysis (per guide)
        if "high_jitter" in issues or "packet_loss" in issues or "high_rtt" in issues:
            root_cause = "NETWORK_DEGRADATION"
            remediation = "Check carrier connection, investigate jitter/packet loss (Guide Section 3)"
        elif "low_mos" in issues and "audio_quality" in issues:
            root_cause = "AUDIO_PROCESSING"
            remediation = "Review AGC/noise suppression settings, check codec chain (Guide Section 7)"
        elif "poor_turn_timing" in issues:
            root_cause = "TURN_TAKING"
            remediation = "Tune VAD thresholds and response gaps (Guide Section 6)"
        else:
            root_cause = "MULTIPLE_FACTORS"
            remediation = "Investigate audio, network, and timing metrics"

        return {
            "overall_rating": overall_rating,
            "user_experience": user_experience,
            "issue_count": len(issues),
            "issues": issues,
            "root_cause": root_cause,
            "recommended_remediation": remediation
        }

    def _emit_structured_log(self, event: Dict, level: int = logging.INFO):
        """
        Emit structured log event as JSON.

        This format is compatible with Azure Log Analytics ingestion.
        """
        # Format as JSON for structured logging
        json_event = json.dumps(event, indent=None)

        # Log at appropriate level
        logger.log(level, json_event)

    def create_kusto_query_example(self) -> str:
        """
        Generate example Kusto query for Log Analytics.

        Returns query string that can be used to analyze quality issues
        as shown in Guide Section 4.
        """
        return f"""
// Example Kusto query for analyzing call quality issues
// Based on Azure S2S Voice Agent Quality Guide Section 4

// Find calls with network issues (jitter > 30ms, packet loss > 10%, RTT > 500ms)
CallDiagnostics
| where event_type == "call_end"
| where company_id == "{self.company_id}"
| extend jitter = toreal(data.network.jitter_avg_ms)
| extend packetLoss = toreal(data.network.packet_loss_rate)
| extend rtt = toreal(data.network.round_trip_time_ms)
| where jitter > 30 or packetLoss > 0.10 or rtt > 500
| project
    timestamp,
    call_id,
    jitter,
    packetLoss,
    rtt,
    overallQuality = tostring(data.overall_quality.overall_rating)
| summarize count() by bin(timestamp, 5m), overallQuality
"""
