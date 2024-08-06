#!/bin/sh

# Export current data
python manage.py dumpdata > fixtures/data.json

# Reset database (you might need to adapt this to your specific needs)
python manage.py flush --no-input

# Load data from JSON file
python manage.py loaddata fixtures/data.json

echo "Database reset and data loaded successfully."