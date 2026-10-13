## Mantra fingerprint agent

Staff fingerprint login uses the local Windows agent in
`biometric_agent/agent.py`. Install the Mantra scanner driver and SDK on the
login terminal, then start the agent with the project virtual environment:

```powershell
.\venv\Scripts\python.exe biometric_agent\agent.py
```

The default SDK path is
`C:\Program Files\Mantra\MFS100\Driver\MFS100Test\MANTRA.MFS100.dll`. If the
SDK is installed elsewhere, set `MANTRA_SDK_PATH` before starting the agent.
Check `http://127.0.0.1:5001/api/status` before testing a staff login.

`BIOMETRIC_MOCK_MODE` defaults to `false`, so inmate and visitor operations
use the scanner agent. The legacy `System Administrator` login simulation is
controlled separately by `BIOMETRIC_LOGIN_SIMULATION=true`; every other staff
role uses the scanner agent, including first-time fingerprint enrolment. The
agent performs template matching through the Mantra SDK; the application does
not use byte-level template similarity for hardware operations.