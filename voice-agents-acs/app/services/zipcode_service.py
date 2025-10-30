"""
ZIP Code Lookup Service
Loads us-zipcodes.csv and provides lookup functionality
"""
import os
import csv
import logging

logger = logging.getLogger(__name__)


class ZipcodeService:
    """Manages ZIP code lookups"""

    def __init__(self):
        self.zipcode_data = {}
        self.csv_path = "data/us-zipcodes.csv"
        self._load_zipcode_data()

    def _load_zipcode_data(self):
        """Load ZIP code data from CSV"""
        try:
            # Check if file exists in data/ directory
            if not os.path.exists(self.csv_path):
                # Try parent directory
                parent_path = os.path.join(os.path.dirname(__file__), '../..', '..', 'data', 'us-zipcodes.csv')
                if os.path.exists(parent_path):
                    self.csv_path = parent_path
                else:
                    logger.error(f"❌ ZIP code CSV not found at {self.csv_path} or {parent_path}")
                    return

            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    zipcode = row['zipcode']
                    self.zipcode_data[zipcode] = {
                        'city': row['city'],
                        'state': row['state']
                    }

            logger.info(f"✅ Loaded {len(self.zipcode_data)} ZIP codes from {self.csv_path}")

        except Exception as e:
            logger.error(f"❌ Failed to load ZIP code data: {e}")

    def lookup(self, zipcode: str) -> dict:
        """
        Look up city and state for a ZIP code.

        Args:
            zipcode: 5-digit ZIP code as string

        Returns:
            dict with 'city' and 'state', or None if not found
        """
        zipcode = str(zipcode).strip().zfill(5)  # Ensure 5 digits with leading zeros
        return self.zipcode_data.get(zipcode)
