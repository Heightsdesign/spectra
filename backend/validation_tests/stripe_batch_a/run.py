"""Run ONLY the DDL-free batch A suite; never load tests/conftest.py."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
os.environ['SELBY_STRIPE_BATCH_A_RUN_ID'] = run_id

import pytest

output = ROOT / 'validation_artifacts' / 'stripe_batch_a' / run_id
output.mkdir(parents=True)


class Results:
    def __init__(self):
        self.entries = []

    def pytest_runtest_logreport(self, report):
        self.entries.append({'test': report.nodeid, 'phase': report.when,
                             'outcome': report.outcome, 'duration_seconds': round(report.duration, 4)})


results = Results()
test_file = 'test_shipment_corrections.py' if '--shipment-corrections' in sys.argv else 'test_batch_a.py'
code = pytest.main([
    str(ROOT / 'validation_tests' / 'stripe_batch_a' / test_file),
    '--confcutdir=' + str(ROOT / 'validation_tests' / 'stripe_batch_a'),
    '-c', str(ROOT / 'pytest.ini'), '-p', 'no:cacheprovider', '-q', '-ra', '--tb=short',
    '--basetemp=' + str(output / 'tmp'),
], plugins=[results])
summary = {'run_id': run_id, 'exit_code': int(code),
           'passed': sum(row['phase'] == 'call' and row['outcome'] == 'passed' for row in results.entries),
           'failed_or_error_phases': sum(row['outcome'] == 'failed' for row in results.entries),
           'skipped': sum(row['outcome'] == 'skipped' for row in results.entries),
           'results': results.entries}
(output / 'results.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
(ROOT / 'validation_artifacts' / 'stripe_batch_a' / 'latest.json').write_text(json.dumps({'run_id': run_id, 'report_directory': str(output), 'exit_code': int(code)}, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in summary.items() if key != 'results'}))
sys.exit(int(code))
