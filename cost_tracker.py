"""
Cost Tracking Module for Voice Agents Platform

Tracks and calculates costs for:
- Azure OpenAI Realtime API usage
- SignalWire telephony
- Azure Container Apps compute
- Azure Blob Storage

Pricing as of Nov 2024:
- gpt-realtime-mini input audio: $0.06 per million audio tokens
- gpt-realtime-mini output audio: $0.24 per million audio tokens
- gpt-realtime-mini text input: $0.60 per million tokens
- gpt-realtime-mini text output: $2.40 per million tokens
- SignalWire inbound: $0.0085 per minute
- Container Apps: ~$0.0002 per minute (estimated)
- Blob Storage: negligible per call
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
import os

logger = logging.getLogger(__name__)


@dataclass
class CallCostBreakdown:
    """Detailed cost breakdown for a single call"""
    call_sid: str
    company_id: str
    start_time: str
    end_time: str
    duration_seconds: float

    # Token usage
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    input_text_tokens: int = 0
    output_text_tokens: int = 0

    # Costs (USD)
    openai_input_audio_cost: float = 0.0
    openai_output_audio_cost: float = 0.0
    openai_input_text_cost: float = 0.0
    openai_output_text_cost: float = 0.0
    signalwire_cost: float = 0.0
    container_apps_cost: float = 0.0
    storage_cost: float = 0.0

    # Totals
    total_openai_cost: float = 0.0
    total_telephony_cost: float = 0.0
    total_infrastructure_cost: float = 0.0
    total_cost: float = 0.0

    # Cost per minute
    cost_per_minute: float = 0.0


class CostTracker:
    """Tracks and calculates costs for voice agent calls"""

    # Pricing constants (USD)
    # OpenAI Realtime API (gpt-realtime-mini)
    PRICE_INPUT_AUDIO_PER_MILLION = 0.06
    PRICE_OUTPUT_AUDIO_PER_MILLION = 0.24
    PRICE_INPUT_TEXT_PER_MILLION = 0.60
    PRICE_OUTPUT_TEXT_PER_MILLION = 2.40

    # SignalWire (typical rates - adjust based on your plan)
    PRICE_SIGNALWIRE_PER_MINUTE = 0.0085

    # Azure infrastructure (estimates)
    PRICE_CONTAINER_APPS_PER_MINUTE = 0.0002
    PRICE_STORAGE_PER_CALL = 0.0001

    def __init__(self, config_manager=None):
        """Initialize cost tracker

        Args:
            config_manager: Optional ConfigManager instance for saving cost data to blob storage
        """
        self.config_manager = config_manager
        self.call_costs: Dict[str, CallCostBreakdown] = {}

    def start_call_tracking(self, call_sid: str, company_id: str) -> None:
        """Start tracking costs for a call

        Args:
            call_sid: Unique call identifier
            company_id: Company ID for the call
        """
        self.call_costs[call_sid] = CallCostBreakdown(
            call_sid=call_sid,
            company_id=company_id,
            start_time=datetime.now(timezone.utc).isoformat(),
            end_time="",
            duration_seconds=0.0
        )
        logger.info(f"💰 Started cost tracking for call {call_sid}")

    def update_token_usage(
        self,
        call_sid: str,
        input_audio_tokens: int = 0,
        output_audio_tokens: int = 0,
        input_text_tokens: int = 0,
        output_text_tokens: int = 0
    ) -> None:
        """Update token usage for a call

        Args:
            call_sid: Call identifier
            input_audio_tokens: Audio tokens consumed (input)
            output_audio_tokens: Audio tokens generated (output)
            input_text_tokens: Text tokens consumed (input)
            output_text_tokens: Text tokens generated (output)
        """
        if call_sid not in self.call_costs:
            logger.warning(f"Call {call_sid} not found in cost tracker")
            return

        cost = self.call_costs[call_sid]
        cost.input_audio_tokens += input_audio_tokens
        cost.output_audio_tokens += output_audio_tokens
        cost.input_text_tokens += input_text_tokens
        cost.output_text_tokens += output_text_tokens

    def finalize_call_costs(self, call_sid: str) -> Optional[CallCostBreakdown]:
        """Calculate final costs for a call

        Args:
            call_sid: Call identifier

        Returns:
            CallCostBreakdown with calculated costs, or None if call not found
        """
        if call_sid not in self.call_costs:
            logger.warning(f"Call {call_sid} not found in cost tracker")
            return None

        cost = self.call_costs[call_sid]
        cost.end_time = datetime.now(timezone.utc).isoformat()

        # Calculate duration
        start = datetime.fromisoformat(cost.start_time)
        end = datetime.fromisoformat(cost.end_time)
        cost.duration_seconds = (end - start).total_seconds()
        duration_minutes = cost.duration_seconds / 60.0

        # Calculate OpenAI costs
        cost.openai_input_audio_cost = (
            cost.input_audio_tokens / 1_000_000
        ) * self.PRICE_INPUT_AUDIO_PER_MILLION

        cost.openai_output_audio_cost = (
            cost.output_audio_tokens / 1_000_000
        ) * self.PRICE_OUTPUT_AUDIO_PER_MILLION

        cost.openai_input_text_cost = (
            cost.input_text_tokens / 1_000_000
        ) * self.PRICE_INPUT_TEXT_PER_MILLION

        cost.openai_output_text_cost = (
            cost.output_text_tokens / 1_000_000
        ) * self.PRICE_OUTPUT_TEXT_PER_MILLION

        cost.total_openai_cost = (
            cost.openai_input_audio_cost +
            cost.openai_output_audio_cost +
            cost.openai_input_text_cost +
            cost.openai_output_text_cost
        )

        # Calculate telephony costs
        cost.signalwire_cost = duration_minutes * self.PRICE_SIGNALWIRE_PER_MINUTE
        cost.total_telephony_cost = cost.signalwire_cost

        # Calculate infrastructure costs
        cost.container_apps_cost = duration_minutes * self.PRICE_CONTAINER_APPS_PER_MINUTE
        cost.storage_cost = self.PRICE_STORAGE_PER_CALL
        cost.total_infrastructure_cost = cost.container_apps_cost + cost.storage_cost

        # Calculate totals
        cost.total_cost = (
            cost.total_openai_cost +
            cost.total_telephony_cost +
            cost.total_infrastructure_cost
        )

        # Cost per minute
        if duration_minutes > 0:
            cost.cost_per_minute = cost.total_cost / duration_minutes

        # Log cost summary
        logger.info(f"💰 Call {call_sid} cost breakdown:")
        logger.info(f"   Duration: {duration_minutes:.2f} minutes")
        logger.info(f"   OpenAI: ${cost.total_openai_cost:.4f}")
        logger.info(f"   Telephony: ${cost.total_telephony_cost:.4f}")
        logger.info(f"   Infrastructure: ${cost.total_infrastructure_cost:.4f}")
        logger.info(f"   TOTAL: ${cost.total_cost:.4f} (${cost.cost_per_minute:.4f}/min)")

        return cost

    async def save_call_costs(self, call_sid: str) -> bool:
        """Save call costs to blob storage

        Args:
            call_sid: Call identifier

        Returns:
            True if saved successfully, False otherwise
        """
        if call_sid not in self.call_costs:
            return False

        if not self.config_manager:
            logger.warning("ConfigManager not available, cannot save costs to blob storage")
            return False

        cost = self.call_costs[call_sid]

        try:
            # Convert to JSON
            cost_data = {
                "cost_breakdown": asdict(cost),
                "pricing_version": "2024-11",
                "currency": "USD"
            }

            # Save to blob storage in costs container
            blob_name = f"{cost.company_id}/{call_sid}-costs.json"

            if hasattr(self.config_manager, 'blob_service_client') and self.config_manager.blob_service_client:
                # Create costs container if it doesn't exist
                container_name = "call-costs"

                blob_client = self.config_manager.blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_name
                )

                cost_json = json.dumps(cost_data, indent=2)
                blob_client.upload_blob(cost_json.encode('utf-8'), overwrite=True)

                logger.info(f"💾 Saved cost data for {call_sid} to blob storage")
                return True
            else:
                logger.warning("Blob storage client not available")
                return False

        except Exception as e:
            logger.error(f"Failed to save cost data for {call_sid}: {e}")
            return False

    def get_daily_summary(self, date: str = None) -> Dict[str, Any]:
        """Get cost summary for a specific date

        Args:
            date: Date in YYYY-MM-DD format (defaults to today)

        Returns:
            Dictionary with daily cost summary
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Filter calls for the specified date
        daily_calls = [
            cost for cost in self.call_costs.values()
            if cost.start_time.startswith(date)
        ]

        if not daily_calls:
            return {
                "date": date,
                "total_calls": 0,
                "total_cost": 0.0
            }

        # Calculate totals
        total_cost = sum(c.total_cost for c in daily_calls)
        total_duration = sum(c.duration_seconds for c in daily_calls) / 60.0  # minutes
        avg_cost_per_call = total_cost / len(daily_calls) if daily_calls else 0
        avg_duration = total_duration / len(daily_calls) if daily_calls else 0

        return {
            "date": date,
            "total_calls": len(daily_calls),
            "total_duration_minutes": round(total_duration, 2),
            "total_cost": round(total_cost, 4),
            "avg_cost_per_call": round(avg_cost_per_call, 4),
            "avg_duration_minutes": round(avg_duration, 2),
            "breakdown": {
                "openai": round(sum(c.total_openai_cost for c in daily_calls), 4),
                "telephony": round(sum(c.total_telephony_cost for c in daily_calls), 4),
                "infrastructure": round(sum(c.total_infrastructure_cost for c in daily_calls), 4)
            }
        }


# Global cost tracker instance
_cost_tracker: Optional[CostTracker] = None


def get_cost_tracker(config_manager=None) -> CostTracker:
    """Get or create the global cost tracker instance

    Args:
        config_manager: Optional ConfigManager instance

    Returns:
        CostTracker instance
    """
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker(config_manager)
    return _cost_tracker
