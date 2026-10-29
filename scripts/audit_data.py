"""Audit standard market data; --strict returns nonzero when requirements fail."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from just_alpha101.data import load_audited_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data/processed/wiki_diagnostic.parquet')
    parser.add_argument('--provenance', type=Path,
                        help='JSON metadata object, or prior audit containing a provenance object')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/data_audit.json')
    parser.add_argument('--start', default='2010-01-04')
    parser.add_argument('--end', default='2013-12-31')
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()
    evidence = args.provenance
    default_data = ROOT / 'data/processed/wiki_diagnostic.parquet'
    if evidence is None and args.data.resolve() == default_data.resolve():
        known_evidence = ROOT / 'reports/data_audit.json'
        if known_evidence.exists():
            evidence = known_evidence
    _, result = load_audited_data(args.data, evidence, start=args.start, end=args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'strict_data_ready': result['strict_data_ready'],
                      'failed_checks': [key for key, value in result['checks'].items() if not value['passed']]}))
    if args.strict and not result['strict_data_ready']:
        raise SystemExit(2)
