"""Materialize the tracked verifier and its small concurrency helper as one file."""
from pathlib import Path


def verifier_source():
    root = Path(__file__).resolve().parent
    source = (root / 'nrt_swimprofiles_verify.ts').read_text()
    marker = "import {mapLimit} from './nrt_verify_concurrency.mjs';"
    if source.count(marker) != 1:
        raise ValueError('Verifier concurrency import changed; update bundler explicitly')
    helper = (root / 'nrt_verify_concurrency.mjs').read_text()
    return source.replace(marker, helper.replace('export async function mapLimit', 'async function mapLimit', 1))
