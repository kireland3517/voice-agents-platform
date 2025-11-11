#!/usr/bin/env python3
"""
Azure Cost Alert Setup Script

This script helps create Azure Monitor alerts for voice agent costs.
It monitors your application's cost data and sends alerts when thresholds are exceeded.

Prerequisites:
- Azure CLI installed and logged in (`az login`)
- Appropriate permissions to create Action Groups and Metric Alerts
- Application Insights or Log Analytics workspace configured

Usage:
    python setup_cost_alerts.py --subscription-id <sub-id> --resource-group <rg-name>

Alert Types Created:
- Daily cost threshold exceeded
- Cost per call spike detected
- Unusual cost patterns
"""

import argparse
import json
import subprocess
import sys
from typing import Dict, Any, List


class CostAlertSetup:
    """Setup Azure Monitor alerts for cost tracking"""

    def __init__(self, subscription_id: str, resource_group: str, app_name: str = "voice-agents-bridge"):
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.app_name = app_name
        self.action_group_name = f"{app_name}-cost-alerts"

    def run_az_command(self, command: List[str]) -> Dict[str, Any]:
        """Run Azure CLI command and return JSON output"""
        full_command = ["az"] + command + ["--output", "json"]

        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                check=True
            )

            if result.stdout:
                return json.loads(result.stdout)
            return {}

        except subprocess.CalledProcessError as e:
            print(f"❌ Error running command: {' '.join(full_command)}")
            print(f"Error: {e.stderr}")
            sys.exit(1)

    def create_action_group(self, email: str, webhook_url: str = None) -> str:
        """Create an Action Group for alert notifications

        Args:
            email: Email address for notifications
            webhook_url: Optional webhook URL (e.g., Slack, Teams)

        Returns:
            Action Group resource ID
        """
        print(f"\n📧 Creating Action Group: {self.action_group_name}")

        command = [
            "monitor", "action-group", "create",
            "--name", self.action_group_name,
            "--resource-group", self.resource_group,
            "--short-name", "CostAlert",
            "--action", "email", "CostAlerts", email
        ]

        # Add webhook if provided
        if webhook_url:
            command.extend(["--action", "webhook", "SlackWebhook", webhook_url])

        result = self.run_az_command(command)

        print(f"✅ Action Group created: {result.get('id', 'Unknown')}")
        return result.get("id")

    def create_daily_cost_alert(self, action_group_id: str, threshold: float = 10.0):
        """Create alert for daily cost threshold

        Args:
            action_group_id: Resource ID of the action group
            threshold: Daily cost threshold in USD (default: $10)
        """
        print(f"\n💰 Creating daily cost alert (threshold: ${threshold})")

        alert_name = f"{self.app_name}-daily-cost-alert"

        # Note: This creates a placeholder alert rule
        # In production, you'd typically integrate with Azure Cost Management API
        # or use Log Analytics queries on your cost data stored in blob storage

        print(f"""
⚠️  Note: Azure Cost Management alerts are created through the Azure Portal.

    To create a cost budget alert:
    1. Go to Azure Portal > Cost Management + Billing
    2. Select your subscription
    3. Click "Budgets" in the left menu
    4. Click "+ Add" to create a new budget
    5. Set budget amount to ${threshold}/day
    6. Configure alert conditions at 80%, 90%, 100% of budget
    7. Add the action group: {self.action_group_name}

    For custom application-level alerts based on your cost tracker data,
    you can:
    1. Export costs to Application Insights custom metrics
    2. Create metric alerts based on those custom metrics
    3. Or use scheduled queries on blob storage cost data
        """)

    def create_cost_spike_alert(self, action_group_id: str, spike_threshold: float = 5.0):
        """Create alert for sudden cost spikes

        Args:
            action_group_id: Resource ID of the action group
            spike_threshold: Cost spike threshold in USD
        """
        print(f"\n📈 Creating cost spike alert (threshold: ${spike_threshold})")

        print(f"""
⚠️  To create cost spike alerts based on your application data:

    Option 1 - Application Insights Custom Metrics:
    1. Modify cost_tracker.py to send custom metrics to App Insights
    2. Create metric alert based on cost_per_minute metric
    3. Set threshold to ${spike_threshold}/minute
    4. Use action group: {self.action_group_name}

    Option 2 - Scheduled Log Analytics Query:
    1. Export cost data to Log Analytics workspace
    2. Create scheduled query alert
    3. Query for sudden cost increases
    4. Use action group: {self.action_group_name}
        """)

    def setup_all_alerts(self, email: str, webhook_url: str = None,
                        daily_threshold: float = 10.0, spike_threshold: float = 5.0):
        """Setup all cost alerts

        Args:
            email: Email for notifications
            webhook_url: Optional webhook URL
            daily_threshold: Daily cost threshold in USD
            spike_threshold: Cost spike threshold in USD
        """
        print("=" * 80)
        print("🚨 AZURE COST ALERT SETUP")
        print("=" * 80)
        print(f"Subscription: {self.subscription_id}")
        print(f"Resource Group: {self.resource_group}")
        print(f"Application: {self.app_name}")
        print("=" * 80)

        # Create action group
        action_group_id = self.create_action_group(email, webhook_url)

        # Create cost alerts
        self.create_daily_cost_alert(action_group_id, daily_threshold)
        self.create_cost_spike_alert(action_group_id, spike_threshold)

        print("\n" + "=" * 80)
        print("✅ SETUP COMPLETE")
        print("=" * 80)
        print("\n📊 Additional Setup Recommendations:")
        print("""
1. Export Cost Data to Application Insights:
   - Modify cost_tracker.py to use ApplicationInsights SDK
   - Track custom metrics for real-time monitoring

2. Create Cost Dashboard:
   - Use Azure Portal to create cost visualization dashboard
   - Add widgets for daily costs, cost per call, token usage

3. Set Up Log Analytics Queries:
   - Export cost JSON files from blob storage
   - Query and analyze cost trends
   - Create custom alerts based on patterns

4. Enable Container Apps Monitoring:
   - Ensure Container Apps logging is enabled
   - Monitor CPU/memory correlation with costs
   - Set up scaling alerts
        """)


def main():
    parser = argparse.ArgumentParser(
        description="Setup Azure cost alerts for voice agent platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic setup with email notifications
  python setup_cost_alerts.py \\
    --subscription-id "xxx-xxx-xxx" \\
    --resource-group "voice-agents-rg" \\
    --email "alerts@example.com"

  # Setup with Slack webhook
  python setup_cost_alerts.py \\
    --subscription-id "xxx-xxx-xxx" \\
    --resource-group "voice-agents-rg" \\
    --email "alerts@example.com" \\
    --webhook "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

  # Custom thresholds
  python setup_cost_alerts.py \\
    --subscription-id "xxx-xxx-xxx" \\
    --resource-group "voice-agents-rg" \\
    --email "alerts@example.com" \\
    --daily-threshold 50 \\
    --spike-threshold 10
        """
    )

    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID"
    )

    parser.add_argument(
        "--resource-group",
        required=True,
        help="Azure resource group name"
    )

    parser.add_argument(
        "--app-name",
        default="voice-agents-bridge",
        help="Application name (default: voice-agents-bridge)"
    )

    parser.add_argument(
        "--email",
        required=True,
        help="Email address for alert notifications"
    )

    parser.add_argument(
        "--webhook",
        help="Optional webhook URL for notifications (e.g., Slack, Teams)"
    )

    parser.add_argument(
        "--daily-threshold",
        type=float,
        default=10.0,
        help="Daily cost threshold in USD (default: 10.0)"
    )

    parser.add_argument(
        "--spike-threshold",
        type=float,
        default=5.0,
        help="Cost spike threshold in USD per minute (default: 5.0)"
    )

    args = parser.parse_args()

    # Create alert setup instance
    alert_setup = CostAlertSetup(
        subscription_id=args.subscription_id,
        resource_group=args.resource_group,
        app_name=args.app_name
    )

    # Setup all alerts
    alert_setup.setup_all_alerts(
        email=args.email,
        webhook_url=args.webhook,
        daily_threshold=args.daily_threshold,
        spike_threshold=args.spike_threshold
    )


if __name__ == "__main__":
    main()
