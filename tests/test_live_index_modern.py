import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from live_result_sources import discover, parse_lenex

ROW = '''<tr><td class="tdStatus">Finished</td>
<td class="tdDate"><a href="/11346/"><span class="dateLong">17 Oct 2026</span>
<span class="dateShort"><span>17</span><span>Oct</span></span></a></td>
<td class="tdCourse"><a href="/11346/"><span class="course">25m</span></a></td>
<td class="tdName"><a href="/11346/"><span class="name">Fjarðarmót 2026</span>
<span class="meta"><span class="flag">🇮🇸</span>Hafnarfjörður ISL · 25m</span></a></td>
<td class="tdCity"><a href="/11346/"><span class="flag">🇮🇸</span>Hafnarfjörður
<span class="nation">ISL</span></a></td></tr>'''


class ModernDiscovery(unittest.TestCase):
    def test_responsive_dates_and_locations_are_not_duplicated(self):
        rows = discover(ROW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['start_date'], '2026-10-17')
        self.assertEqual(rows[0]['city'], 'Hafnarfjörður')
        self.assertEqual(rows[0]['name'], 'Fjarðarmót 2026')
        self.assertEqual(rows[0]['country'], 'ISL')

    def test_repeated_source_id_is_only_discovered_once(self):
        self.assertEqual(len(discover(ROW + ROW)), 1)

    def test_conflicting_source_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            discover(ROW + ROW.replace('Fjarðarmót 2026', 'Another competition'))

    def test_unrecognized_layout_does_not_silently_report_zero(self):
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            discover('<a href="/11346/">Competition</a>')

    def test_open_water_is_not_misrepresented_as_pool_swimming(self):
        self.assertEqual(discover(ROW.replace('25m', 'OW')), [])

    def test_placeholder_event_does_not_discard_valid_swims(self):
        meet = discover(ROW)[0]
        xml = '''<LENEX><MEETS><MEET name="Fjarðarmót 2026" course="SCM">
<SESSIONS><SESSION date="2026-10-17"><EVENTS>
<EVENT eventid="placeholder" number="90"><SWIMSTYLE stroke="UNKNOWN" name="n/a"/></EVENT>
<EVENT eventid="valid" number="1" gender="F" round="TIM"><SWIMSTYLE distance="100" stroke="FREE"/></EVENT>
</EVENTS></SESSION></SESSIONS><CLUBS><CLUB name="Test"><ATHLETES>
<ATHLETE athleteid="1" firstname="Test" lastname="Swimmer" birthdate="2000-01-01" gender="F" nation="ISL">
<RESULTS><RESULT eventid="valid" resultid="1" swimtime="00:01:00.00"/></RESULTS>
</ATHLETE></ATHLETES></CLUB></CLUBS></MEET></MEETS></LENEX>'''.encode()
        report = parse_lenex(xml, meet, 'fixture')
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['rows'][0]['time_seconds'], '60.00')
        self.assertIn('Unsupported LENEX event definition: placeholder', report['holds'])


if __name__ == '__main__':
    unittest.main()
