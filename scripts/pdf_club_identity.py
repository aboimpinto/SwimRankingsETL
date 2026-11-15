"""Reviewed, meet-scoped PDF club codes; never inferred from swimmer membership."""
import json
from pathlib import Path
import re


def resolve_club(row, live_id, mappings=None):
    if row['source_kind'] != 'pdf':
        return row
    if mappings is None:
        mappings = json.loads((Path(__file__).parents[1] / 'config/pdf-club-identities.json').read_text())
    matches = [m for m in mappings if str(live_id) in m['liveIds']
               and row.get('club', '').strip().casefold() == m['code'].casefold()]
    if len(matches) > 1:
        raise ValueError('Ambiguous reviewed PDF club code')
    if not matches:
        return row
    proof = matches[0]
    if (not proof.get('name', '').strip() or not proof.get('sourceUrl', '').startswith('https://')
            or not re.fullmatch('[a-f0-9]{64}', proof.get('sourceHash', ''))):
        raise ValueError('Invalid reviewed PDF club evidence')
    return dict(row, club_identity=proof)


def club_name(row):
    return (row.get('club_identity', {}).get('name') or row.get('club') or '').strip() or None


def race_payload(row):
    return {k: v for k, v in row.items()
            if k not in ('source', 'source_hash', 'athlete_id', 'club', 'club_identity')}
