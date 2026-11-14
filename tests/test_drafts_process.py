"""Task-Manager-style GUI termination and real startup recovery, both editions."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui


@pytest.mark.parametrize('edition', ['owner', 'user'])
def test_killed_gui_process_recovers_at_next_start(tmp_path, edition):
    root = Path(__file__).resolve().parent.parent
    home, ready, result = tmp_path / 'home', tmp_path / 'ready', tmp_path / 'result.json'
    child = r'''
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
import gui_harness as h
home, ready = sys.argv[1:]
g, a = h.start_app(Path(home))
g['set_entry'](g['SO_number_entry'], 'KILLED-GUI-RECOVERY')
g['set_entry'](g['declared_goods_rows'][1][1], '1,')
g['mark_dirty']()
assert g['draft_controller'].flush()
Path(ready).write_text('ready')
while True:
    g['window'].update()
    time.sleep(.02)
'''
    env = dict(os.environ, FSR_EDITION=edition, FSR_SECRET_STORE='')
    proc = subprocess.Popen([sys.executable, '-c', child, str(home), str(ready)],
                            cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < end:
            if proc.poll() is not None:
                pytest.fail('Disposable GUI exited before its draft checkpoint')
            time.sleep(.03)
        assert ready.exists(), 'Disposable GUI did not reach its checkpoint'
        proc.kill()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    recover = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
import gui_harness as h
import fsr_drafts_ui
home, result = sys.argv[1:]
def offer(self):
    values, damaged = self.store.list()
    assert len(values) == 1 and not damaged
    assert self.restore(values[0])
    self.h['recovered_draft'] = True
fsr_drafts_ui.Controller.show = offer
g, a = h.start_app(Path(home))
try:
    end = time.monotonic() + 10
    while not g.get('recovered_draft') and time.monotonic() < end:
        g['window'].update()
        time.sleep(.02)
    assert g.get('recovered_draft'), 'Startup did not offer the account draft'
    Path(result).write_text(json.dumps({'so': g['SO_number_entry'].get(),
        'quantity': g['declared_goods_rows'][1][1].get(),
        'reports': len(g['data_store']().list_reports()), 'editing': g['report_state']['editing']}))
finally:
    h.stop_app(g, a)
'''
    done = subprocess.run([sys.executable, '-c', recover, str(home), str(result)],
                          cwd=root, env=env, capture_output=True, text=True, timeout=40)
    assert done.returncode == 0, 'Fresh GUI process could not recover its draft: ' + done.stderr[-2500:]
    assert json.loads(result.read_text()) == {'so': 'KILLED-GUI-RECOVERY', 'quantity': '1,', 'reports': 0, 'editing': False}
