"""
Text Formatting Utilities for Speech Synthesis
Optimized for elderly customers - ensures clear, natural number reading
"""
import re
from typing import Optional


def format_phone_for_speech(phone: str) -> str:
    """
    Convert phone numbers to speech-friendly format

    Examples:
        +17037778808 -> "seven zero three, seven seven seven, eight eight zero eight"
        (703) 777-8808 -> "seven zero three, seven seven seven, eight eight zero eight"
        703-777-8808 -> "seven zero three, seven seven seven, eight eight zero eight"

    Args:
        phone: Phone number in any format

    Returns:
        Speech-friendly phone number with digits separated and grouped
    """
    if not phone:
        return phone

    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))

    # Remove country code if present (e.g., +1)
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]

    if len(digits) == 10:
        # Format as: "XXX, XXX, XXXX" with spaces between digits
        area = ' '.join(digits[0:3])      # "7 0 3"
        prefix = ' '.join(digits[3:6])    # "7 7 7"
        line = ' '.join(digits[6:10])     # "8 8 0 8"
        return f"{area}, {prefix}, {line}"

    # If not 10 digits, just separate all digits with spaces
    return ' '.join(digits)


def format_address_for_speech(address: str) -> str:
    """
    Convert addresses to speech-friendly format

    Examples:
        "4037 Oak St" -> "four zero three seven Oak Street"
        "123 Main Ave Apt 5" -> "one two three Main Avenue Apartment five"
        "1600 Pennsylvania Ave NW" -> "one six zero zero Pennsylvania Avenue Northwest"

    Args:
        address: Street address

    Returns:
        Speech-friendly address with numbers spoken as digits and abbreviations expanded
    """
    if not address:
        return address

    # Replace street number with digit-by-digit version
    def number_to_digits(match):
        num = match.group(0)
        # For street numbers, speak digit by digit
        return ' '.join(num)

    # Replace standalone numbers (street numbers, apartment numbers, etc.)
    address = re.sub(r'\b\d+\b', number_to_digits, address)

    # Expand common street abbreviations
    abbreviations = {
        r'\bSt\b': 'Street',
        r'\bAve\b': 'Avenue',
        r'\bRd\b': 'Road',
        r'\bDr\b': 'Drive',
        r'\bLn\b': 'Lane',
        r'\bBlvd\b': 'Boulevard',
        r'\bCt\b': 'Court',
        r'\bPl\b': 'Place',
        r'\bTer\b': 'Terrace',
        r'\bPkwy\b': 'Parkway',
        r'\bCir\b': 'Circle',
        r'\bApt\b': 'Apartment',
        r'\bSte\b': 'Suite',
        r'\bBldg\b': 'Building',
        r'\bFl\b': 'Floor',
        r'\bNW\b': 'Northwest',
        r'\bNE\b': 'Northeast',
        r'\bSW\b': 'Southwest',
        r'\bSE\b': 'Southeast',
        r'\bN\b': 'North',
        r'\bS\b': 'South',
        r'\bE\b': 'East',
        r'\bW\b': 'West',
    }

    for abbr, full in abbreviations.items():
        address = re.sub(abbr, full, address, flags=re.IGNORECASE)

    return address


def format_zip_code_for_speech(zip_code: str) -> str:
    """
    Convert ZIP codes to speech-friendly format

    Examples:
        "22030" -> "two two zero three zero"
        "22030-1234" -> "two two zero three zero, one two three four"

    Args:
        zip_code: ZIP code

    Returns:
        Speech-friendly ZIP code with digits separated
    """
    if not zip_code:
        return zip_code

    # Remove non-digit characters except hyphen
    digits = ''.join(c for c in zip_code if c.isdigit() or c == '-')

    # Split on hyphen if present (ZIP+4)
    parts = digits.split('-')

    # Speak each digit separately
    formatted_parts = [' '.join(part) for part in parts]

    # Join with comma for ZIP+4
    return ', '.join(formatted_parts)


def format_dollar_amount_for_speech(amount: str) -> str:
    """
    Convert dollar amounts to speech-friendly format

    Examples:
        "$1,234.56" -> "one thousand two hundred thirty four dollars and fifty six cents"
        "$100" -> "one hundred dollars"
        "$0.50" -> "fifty cents"

    Args:
        amount: Dollar amount as string

    Returns:
        Speech-friendly dollar amount
    """
    if not amount:
        return amount

    # Remove $ and commas
    amount_clean = amount.replace('$', '').replace(',', '')

    try:
        value = float(amount_clean)

        # Separate dollars and cents
        dollars = int(value)
        cents = int(round((value - dollars) * 100))

        result = []

        if dollars > 0:
            result.append(f"{number_to_words(dollars)} dollar{'s' if dollars != 1 else ''}")

        if cents > 0:
            if dollars > 0:
                result.append("and")
            result.append(f"{number_to_words(cents)} cent{'s' if cents != 1 else ''}")

        if not result:
            return "zero dollars"

        return ' '.join(result)

    except ValueError:
        # If parsing fails, return original
        return amount


def number_to_words(num: int) -> str:
    """
    Convert a number to words (simple implementation for small numbers)

    Examples:
        123 -> "one hundred twenty three"
        1000 -> "one thousand"

    Args:
        num: Integer to convert

    Returns:
        Number as words
    """
    if num == 0:
        return "zero"

    # Define word mappings
    ones = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
             "sixteen", "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    def convert_below_1000(n):
        if n == 0:
            return ""
        elif n < 10:
            return ones[n]
        elif n < 20:
            return teens[n - 10]
        elif n < 100:
            return tens[n // 10] + (" " + ones[n % 10] if n % 10 != 0 else "")
        else:
            return ones[n // 100] + " hundred" + (" " + convert_below_1000(n % 100) if n % 100 != 0 else "")

    if num < 1000:
        return convert_below_1000(num)
    elif num < 1000000:
        thousands = num // 1000
        remainder = num % 1000
        result = convert_below_1000(thousands) + " thousand"
        if remainder > 0:
            result += " " + convert_below_1000(remainder)
        return result
    else:
        # For very large numbers, just return the number as is
        return str(num)


def format_text_for_speech(text: str, context: Optional[str] = None) -> str:
    """
    Main formatting function - applies all formatting rules

    Args:
        text: Text to format
        context: Optional context hint (e.g., "phone", "address", "zip")

    Returns:
        Speech-optimized text
    """
    if not text:
        return text

    # If context is specified, use specific formatter
    if context == "phone":
        return format_phone_for_speech(text)
    elif context == "address":
        return format_address_for_speech(text)
    elif context == "zip":
        return format_zip_code_for_speech(text)
    elif context == "currency":
        return format_dollar_amount_for_speech(text)

    # Auto-detect and format
    formatted = text

    # Format phone numbers (detect by pattern) with space preservation
    phone_pattern = r'\+?1?\s*\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})'
    if re.search(phone_pattern, formatted):
        formatted = re.sub(phone_pattern, lambda m: ' ' + format_phone_for_speech(m.group(0)), formatted)

    # Format ZIP codes (5 or 9 digits, possibly with hyphen)
    zip_pattern = r'\b\d{5}(?:-\d{4})?\b'
    formatted = re.sub(zip_pattern, lambda m: format_zip_code_for_speech(m.group(0)), formatted)

    # Format dollar amounts
    dollar_pattern = r'\$[\d,]+\.?\d*'
    formatted = re.sub(dollar_pattern, lambda m: format_dollar_amount_for_speech(m.group(0)), formatted)

    return formatted
