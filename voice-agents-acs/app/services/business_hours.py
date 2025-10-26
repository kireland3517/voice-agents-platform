"""
Business Hours Service
Ported from app.py lines 527-571 with overnight hours support
"""
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


def check_business_hours(company_config: dict) -> tuple[bool, dict]:
    """
    Check if current time is within business hours.
    Supports overnight hours (e.g., 8am-2am).

    Args:
        company_config: Company configuration with business-hours section

    Returns:
        Tuple of (is_business_hours: bool, context: dict)
    """
    business_hours_config = company_config.get('business-hours', {})

    # Get configuration
    timezone_str = business_hours_config.get('timezone', 'US/Eastern')
    business_days = business_hours_config.get('days', [0, 1, 2, 3, 4])  # 0=Monday, 6=Sunday
    open_time_str = business_hours_config.get('open-time', '08:30')
    close_time_str = business_hours_config.get('close-time', '17:00')

    logger.info(f"⚙️ Business hours config: timezone={timezone_str}, days={business_days}, open={open_time_str}, close={close_time_str}")

    try:
        # Get current time in business timezone
        tz = pytz.timezone(timezone_str)
        now_local = datetime.now(tz)

        logger.info(f"🕐 Current time: {now_local.strftime('%A, %B %d, %Y at %I:%M %p %Z')}")

        # Parse open and close times
        open_hour, open_minute = map(int, open_time_str.split(':'))
        close_hour, close_minute = map(int, close_time_str.split(':'))

        # Convert to minutes for easier comparison
        current_time_minutes = now_local.hour * 60 + now_local.minute
        open_time_minutes = open_hour * 60 + open_minute
        close_time_minutes = close_hour * 60 + close_minute

        # Check if hours span midnight (overnight, e.g., 8am-2am)
        is_overnight = close_time_minutes < open_time_minutes

        # Determine if currently in business hours
        current_day = now_local.weekday()
        previous_day = (current_day - 1) % 7

        if is_overnight:
            # Overnight hours (e.g., Mon 8am - Tue 2am)
            # Two scenarios:
            # 1. Current time is after open time on a business day (Mon 8am - Mon 11:59pm)
            # 2. Current time is before close time and YESTERDAY was a business day (Tue 12am - Tue 2am)
            in_hours_today = current_day in business_days and current_time_minutes >= open_time_minutes
            in_hours_from_yesterday = previous_day in business_days and current_time_minutes < close_time_minutes
            is_business_hours = in_hours_today or in_hours_from_yesterday

            logger.info(f"📅 Overnight hours detected: open={open_time_str}, close={close_time_str}")
            logger.info(f"📅 Business hours check: Day={now_local.strftime('%A')} ({current_day}), Time={now_local.strftime('%H:%M')}, in_hours_today={in_hours_today}, in_hours_from_yesterday={in_hours_from_yesterday}, is_business_hours={is_business_hours}")
        else:
            # Standard hours (e.g., Mon 8am - Mon 5pm)
            is_business_day = current_day in business_days
            is_within_hours = open_time_minutes <= current_time_minutes < close_time_minutes
            is_business_hours = is_business_day and is_within_hours

            logger.info(f"📅 Standard hours: Day={now_local.strftime('%A')} ({current_day}), Time={now_local.strftime('%H:%M')}, is_business_day={is_business_day}, is_within_hours={is_within_hours}, is_business_hours={is_business_hours}")

        # Build context dict
        context = {
            'current_time': now_local.strftime('%A, %B %d, %Y at %I:%M %p %Z'),
            'is_business_hours': is_business_hours,
            'is_overnight': is_overnight,
            'timezone': timezone_str,
            'open_time': open_time_str,
            'close_time': close_time_str,
            'business_days': business_days
        }

        return is_business_hours, context

    except Exception as e:
        logger.error(f"❌ Error checking business hours: {e}")
        # Default to closed if error
        return False, {'error': str(e)}


async def get_business_hours_context(company_config: dict) -> str:
    """
    Get business hours context as formatted string for AI prompt.

    Args:
        company_config: Company configuration

    Returns:
        Formatted string describing business hours status
    """
    is_open, context = check_business_hours(company_config)

    if 'error' in context:
        return "BUSINESS HOURS: Unable to determine current business hours status."

    current_time = context['current_time']

    if is_open:
        return f"""BUSINESS HOURS STATUS:
Current Time: {current_time}
Status: OPEN - You can transfer customers to a live agent.
"""
    else:
        return f"""BUSINESS HOURS STATUS:
Current Time: {current_time}
Status: CLOSED - We are currently outside business hours.
- Do NOT offer to transfer to a live agent
- Offer to schedule a callback during business hours
- Collect customer information for follow-up
"""
