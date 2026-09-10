import subprocess

PY = r'C:/Users/cenacai/.workbuddy/binaries/python/versions/3.13.12/python.exe'
SCRIPT = r'C:/Users/cenacai/WorkBuddy/2026-08-31-18-52-03/autopilot-poc/cockpit.py'
LOG = r'C:/Users/cenacai/WorkBuddy/2026-08-31-18-52-03/autopilot-poc/cockpit_dev.log'

with open(LOG, 'w', encoding='utf-8') as f:
    subprocess.Popen(
        [PY, SCRIPT, '--port', '8090', '--host', '127.0.0.1'],
        stdout=f, stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
print("launched detached cockpit ->", LOG)
