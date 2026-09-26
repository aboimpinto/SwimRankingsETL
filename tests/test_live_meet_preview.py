"""Synthetic two-day exports; no network, credentials or database needed."""
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from preview_live_meet import preview, fresh_download, inspect_lenex
from urllib.error import HTTPError

START, END = date(2026, 9, 26), date(2026, 9, 27)


def fixture(rows=(), *, missing_date=False, duplicate=False):
    root = ET.fromstring('''<LENEX><MEETS><MEET name="Synthetic meeting" city="Meilen" nation="SUI" course="SCM">
      <SESSIONS><SESSION date="2026-09-26"><EVENTS><EVENT eventid="1"><SWIMSTYLE distance="50" stroke="FREE" /></EVENT></EVENTS></SESSION>
      <SESSION date="2026-09-27"><EVENTS><EVENT eventid="2"><SWIMSTYLE distance="100" stroke="FREE" /></EVENT></EVENTS></SESSION></SESSIONS>
      <CLUBS><CLUB name="Synthetic club"><ATHLETES><ATHLETE athleteid="1" firstname="Example" lastname="Swimmer" birthdate="2000-01-01"><RESULTS /></ATHLETE></ATHLETES></CLUB></CLUBS>
      </MEET></MEETS></LENEX>''')
    if missing_date:
        root.find('.//SESSION').attrib.pop('date')
    container = root.find('.//RESULTS')
    for rid, event, time in rows:
        ET.SubElement(container, 'RESULT', resultid=rid, eventid=event, swimtime=time)
    if duplicate and rows:
        rid, event, time = rows[0]
        ET.SubElement(container, 'RESULT', resultid=rid, eventid=event, swimtime=time)
    return ET.tostring(root)


DAY1 = [('1', '1', '00:30.00')]
DAY2 = DAY1 + [('2', '2', '01:10.00')]


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)

    def run_preview(self, rows=(), **kwargs):
        return preview(self.output, '123', START, END, data=fixture(rows), source='synthetic', **kwargs)

    def baseline(self):
        return (self.output / '123/baseline.json').read_bytes()

    def test_day_one_repeat_day_two_and_correction(self):
        one = self.run_preview(DAY1, today=START)
        self.assertEqual(one['source_delta'], dict(added=1, removed=0, changed=0, unchanged=0))
        self.assertEqual(one['scheduled_days_without_results'], ['2026-09-27'])
        self.assertEqual(one['scheduled_events_without_results'], ['2'])
        self.assertEqual(one['scheduled_status'], 'ongoing')
        repeat = self.run_preview(DAY1)
        self.assertEqual(repeat['status'], 'unchanged')
        two = self.run_preview(DAY2, today=date(2026, 9, 28))
        self.assertEqual(two['source_delta']['added'], 1)
        self.assertEqual(two['results_by_day'], {'2026-09-26': 1, '2026-09-27': 1})
        self.assertEqual(two['scheduled_days_without_results'], [])
        self.assertEqual(two['scheduled_status'], 'ended_unverified')
        self.assertTrue(two['recheck_required'])
        correction = self.run_preview([DAY1[0], ('2', '2', '01:09.00')])
        self.assertEqual(correction['source_delta']['changed'], 1)
        self.assertEqual(correction['source_delta']['added'], 0)
        self.assertFalse(correction['database_writes'])
        self.assertFalse(correction['import_executed'])
        self.assertEqual(len(list((self.output / '123/reports').glob('*.json'))), 4)
        self.assertTrue((self.output / '123/latest.md').exists())

    def test_empty_schedule_is_not_import_ready(self):
        result = self.run_preview(today=END)
        self.assertEqual(result['status'], 'waiting_for_results')
        self.assertEqual(result['import_readiness'], 'hold')
        self.assertFalse((self.output / '123/baseline.json').exists())
        self.assertEqual(result['scheduled_days_without_results'], [str(START), str(END)])

    def test_regression_and_empty_preserve_baseline(self):
        self.run_preview(DAY2)
        before = self.baseline()
        for rows in [DAY1, []]:
            report = self.run_preview(rows)
            self.assertEqual(report['status'], 'held_for_review')
            self.assertEqual(report['import_readiness'], 'hold')
            self.assertEqual(self.baseline(), before)
        self.assertEqual(self.run_preview(DAY2)['status'], 'unchanged')

    def test_failure_preserves_baseline_and_watch(self):
        self.run_preview(DAY1)
        before = self.baseline()
        def fail(_):
            raise OSError('Synthetic download failure')
        result = preview(self.output, '123', START, END, downloader=fail)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(self.baseline(), before)
        self.assertEqual(json.loads((self.output / '123/watch.json').read_text())['end_date'], str(END))

    def test_every_recheck_downloads_again(self):
        responses = iter([fixture(DAY1), fixture(DAY2)])
        calls = []
        def download(live_id):
            calls.append(live_id)
            return next(responses), 'https://example.test/fresh.lxf', []
        preview(self.output, '123', START, END, downloader=download)
        second = preview(self.output, '123', START, END, downloader=download)
        self.assertEqual(calls, ['123', '123'])
        self.assertEqual(second['source_delta']['added'], 1)

    def test_ambiguous_and_undated_results_held(self):
        for data in [fixture(DAY1, duplicate=True), fixture(DAY1, missing_date=True), fixture([('1', '999', '00:30.00')])]:
            report = preview(self.output, '123', START, END, data=data)
            self.assertEqual(report['status'], 'held_for_review')
            self.assertFalse((self.output / '123/baseline.json').exists())

    def test_invalid_or_wrong_meet_keeps_last_good_baseline(self):
        self.run_preview(DAY1)
        before = self.baseline()
        for data in [b'<html>Quota message</html>', b'<!DOCTYPE LENEX><LENEX/>',
                     fixture(DAY1).replace(b'Meilen', b'Another city'),
                     fixture(DAY1).replace(b'2026-09-27', b'2026-10-27')]:
            result = preview(self.output, '123', START, END, data=data)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(self.baseline(), before)

    def test_day_one_only_schedule_still_watches_day_two(self):
        root = ET.fromstring(fixture(DAY1))
        sessions = root.find('.//SESSIONS')
        sessions.remove(sessions[1])
        result = preview(self.output, '123', START, END, data=ET.tostring(root))
        self.assertEqual(result['scheduled_days_without_results'], [str(END)])
        self.assertTrue(result['recheck_required'])

    def test_split_correction_and_relay_results(self):
        root = ET.fromstring(fixture(DAY1))
        splits = ET.SubElement(root.find('.//RESULT'), 'SPLITS')
        split = ET.SubElement(splits, 'SPLIT', distance='25', swimtime='00:14.00')
        relays = ET.SubElement(root.find('.//CLUB'), 'RELAYS')
        relay = ET.SubElement(relays, 'RELAY', relayid='r1')
        results = ET.SubElement(relay, 'RESULTS')
        ET.SubElement(results, 'RESULT', eventid='2', swimtime='02:00.00')
        one = preview(self.output, '123', START, END, data=ET.tostring(root))
        self.assertEqual(one['source_result_elements'], 2)
        split.set('swimtime', '00:13.99')
        two = preview(self.output, '123', START, END, data=ET.tostring(root))
        self.assertEqual(two['source_delta']['changed'], 1)
        self.assertEqual(two['source_delta']['unchanged'], 1)

    def test_cli_recheck_uses_saved_schedule(self):
        self.run_preview(DAY1)
        from preview_live_meet import main
        arguments = ['preview', '--recheck', '--output', str(self.output)]
        with patch('sys.argv', arguments), patch('preview_live_meet.preview', return_value={'status': 'unchanged'}) as call, patch('builtins.print'):
            self.assertEqual(main(), 0)
        call.assert_called_once_with(self.output, '123', START, END)

    def test_zip_lenex_uses_same_parser(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('results.lef', fixture(DAY2))
        self.assertEqual(inspect_lenex(buffer.getvalue())['source_result_elements'], 2)

    def test_fallback_after_404_but_no_bypass_of_auth_or_quota(self):
        class Response(io.BytesIO):
            url = 'https://example.test/Results.lxf'
        for code in [401, 403, 429]:
            with patch('preview_live_meet.urlopen', side_effect=HTTPError('url', code, 'no', {}, None)) as request:
                with self.assertRaises(ValueError):
                    fresh_download('123')
                self.assertEqual(request.call_count, 1)
        with patch('preview_live_meet.urlopen', side_effect=[HTTPError('url', 404, 'missing', {}, None), Response(fixture(DAY1))]) as request:
            data, _, failures = fresh_download('123')
            self.assertEqual(request.call_count, 2)
            self.assertEqual(data, fixture(DAY1))
            self.assertIn('HTTP 404', failures[0])

    def test_offline_cli_does_not_need_database_dependencies(self):
        path = self.output / 'fixture.lxf'
        path.write_bytes(fixture(DAY1))
        script = Path(__file__).resolve().parents[1] / 'scripts/preview_live_meet.py'
        # -S disables site packages: psycopg2 and other DB clients are unavailable.
        result = subprocess.run([sys.executable, '-S', str(script), '--live-id', '123', '--start', str(START),
                                 '--end', str(END), '--lxf-file', str(path), '--output', str(self.output)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)[0]['import_executed'])
        self.assertEqual(path.read_bytes(), fixture(DAY1))


if __name__ == '__main__':
    unittest.main()
