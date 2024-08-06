@echo off
REM Export current data
python manage.py dumpdata > fixtures\data_new.json

REM Reset database (you might need to adapt this to your specific needs)
python manage.py flush_except_superuser

REM Load data from JSON file
python manage.py loaddata fixtures\data.json

echo Database reset and data loaded successfully.
pause