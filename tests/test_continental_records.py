import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import refresh_continental_records as c


def bundle(course='LCM'):
    downloads=[]
    for gender,number in c.GENDERS.items():
        rows=[] if gender=='X' else [dict(id='fixture-'+gender,recordName='AM',pool=c.POOLS[course],
            disciplineGender=number,disciplineGroup='Freestyle',disciplineDistance=100,
            disciplineName='100',isRelay=False,time='00:00:50.0100000',date='2026-01-01T00:00:00',
            recordUpdated='2026-01-02T12:00:00',recordStatus=2,preferredFirstName='Fixture',
            preferredLastName='Holder',nationalityCode='CAN')]
        downloads.append(dict(gender=gender,page=1,url=c.record_url('AM',course,gender),
            payload=dict(query=dict(poolConfiguration=c.POOLS[course],disciplineGender=number,page=1,current=True),
                         records=rows,totalRowCount=len(rows),generatedOn='first run')))
    return dict(provider='World Aquatics',code='AM',course=course,downloads=downloads)


class Continental(unittest.TestCase):
    def test_approved_records_preserve_course_time_and_no_invented_splits(self):
        rows,_=c.parse_bundle(bundle('SCM'),'AM','SCM')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].course,'SCM')
        self.assertEqual(rows[0].comparison_scope,'americas')
        self.assertEqual(float(rows[0].time_seconds),50.01)
        self.assertEqual(rows[0].splits,())
        self.assertEqual(rows[0].nation,None)
        self.assertEqual(rows[0].athlete_nation,'CAN')
        self.assertIn('pool=SCM',c.record_url('AM','SCM','F'))
        self.assertNotIn('poolConfiguration',c.record_url('AM','SCM','F'))

    def test_semantic_replay_ignores_response_generation_and_detects_time_corrections(self):
        original=bundle();_,first=c.parse_bundle(original,'AM','LCM')
        original['downloads'][0]['payload']['generatedOn']='next week'
        _,replay=c.parse_bundle(original,'AM','LCM');self.assertEqual(first,replay)
        original['downloads'][0]['payload']['records'][0]['time']='00:00:49.0000000'
        self.assertNotEqual(first,c.parse_bundle(original,'AM','LCM')[1])

    def test_ties_are_retained_and_pending_records_excluded(self):
        data=bundle();row=data['downloads'][0]['payload']['records'][0]
        row['recordName']='=AM';row['recordStatus']=1
        rows,_=c.parse_bundle(data,'AM','LCM')
        self.assertEqual(next(r for r in rows if r.gender=='M').comparison_scope,'excluded')

    def test_mismatched_course_scope_truncated_and_duplicate_records_rejected(self):
        for mutate in [
            lambda d:d['downloads'][0]['payload']['query'].update(poolConfiguration=1),
            lambda d:d['downloads'][0]['payload']['records'][0].update(recordName='NR'),
            lambda d:d['downloads'][0]['payload'].update(totalRowCount=2),
            lambda d:d['downloads'].pop(),
            lambda d:d['downloads'][0]['payload']['records'][0].update(time='bad'),
            lambda d:d['downloads'][0]['payload']['records'][0].update(isRelay=True),
        ]:
            data=bundle();mutate(data)
            with self.assertRaises(ValueError):c.parse_bundle(data,'AM','LCM')

    def test_relay_distance_is_per_leg(self):
        data=bundle();row=data['downloads'][0]['payload']['records'][0]
        row.update(isRelay=True,disciplineName='4x100',disciplineGroup='Medley Relay')
        rows,_=c.parse_bundle(data,'AM','LCM')
        relay=next(r for r in rows if r.gender=='M')
        self.assertEqual((relay.distance,relay.relay_count,relay.stroke),(100,4,'MEDLEY'))
