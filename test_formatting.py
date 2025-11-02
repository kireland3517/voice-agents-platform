"""
Test script for text_formatting.py
Run this to verify phone numbers, addresses, and ZIP codes format correctly for speech
"""
import sys
import io

# Fix Windows console encoding to support emojis
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from text_formatting import (
    format_phone_for_speech,
    format_address_for_speech,
    format_zip_code_for_speech,
    format_text_for_speech
)


def test_phone_formatting():
    """Test phone number formatting"""
    print("\n📞 PHONE NUMBER FORMATTING TESTS")
    print("=" * 60)

    test_cases = [
        "+17037778808",
        "(703) 777-8808",
        "703-777-8808",
        "7037778808",
        "1-877-555-1234",
    ]

    for phone in test_cases:
        formatted = format_phone_for_speech(phone)
        print(f"Input:  {phone}")
        print(f"Speech: {formatted}")
        print()


def test_address_formatting():
    """Test address formatting"""
    print("\n🏠 ADDRESS FORMATTING TESTS")
    print("=" * 60)

    test_cases = [
        "4037 Oak St",
        "123 Main Ave Apt 5",
        "1600 Pennsylvania Ave NW",
        "42 Maple Dr",
        "9876 S Highland Blvd Suite 200",
    ]

    for address in test_cases:
        formatted = format_address_for_speech(address)
        print(f"Input:  {address}")
        print(f"Speech: {formatted}")
        print()


def test_zip_code_formatting():
    """Test ZIP code formatting"""
    print("\n📮 ZIP CODE FORMATTING TESTS")
    print("=" * 60)

    test_cases = [
        "22030",
        "22030-1234",
        "12345",
        "00501",  # ZIP with leading zeros
    ]

    for zip_code in test_cases:
        formatted = format_zip_code_for_speech(zip_code)
        print(f"Input:  {zip_code}")
        print(f"Speech: {formatted}")
        print()


def test_auto_formatting():
    """Test automatic formatting detection"""
    print("\n🔍 AUTOMATIC DETECTION TESTS")
    print("=" * 60)

    test_cases = [
        "Please call me at (703) 777-8808",
        "My ZIP code is 22030",
        "I live at 4037 Oak St",
        "Send check for $1,234.56",
    ]

    for text in test_cases:
        formatted = format_text_for_speech(text)
        print(f"Input:  {text}")
        print(f"Speech: {formatted}")
        print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TEXT FORMATTING FOR SPEECH - TEST SUITE")
    print("Optimized for Elderly Customers")
    print("=" * 60)

    test_phone_formatting()
    test_address_formatting()
    test_zip_code_formatting()
    test_auto_formatting()

    print("\n" + "=" * 60)
    print("✅ ALL TESTS COMPLETE")
    print("=" * 60)
