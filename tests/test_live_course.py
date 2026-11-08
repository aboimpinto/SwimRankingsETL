"""Open-water results must not enter pool comparisons."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from import_live_swimrankings_meet import get_pool_length, extract_meet_metadata
from xml.etree.ElementTree import fromstring


class CourseTests(unittest.TestCase):
    def test_open_water_is_distinct_from_pool_courses(self):
        root = fromstring('<LENEX><MEETS><MEET name="Open water" course="OPEN">'
                          '<SESSIONS><SESSION date="2026-08-15"/></SESSIONS>'
                          '</MEET></MEETS></LENEX>')
        self.assertEqual(extract_meet_metadata(root)['pool_length'], 0)
        self.assertEqual(get_pool_length('SCM'), 25)
        self.assertEqual(get_pool_length('LCM'), 50)
