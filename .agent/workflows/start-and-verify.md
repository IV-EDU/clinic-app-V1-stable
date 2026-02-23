---
description: how to start the clinic app server and run browser verification
---

# Start the App and Verify in Browser

## Why This Exists
The Flask app must be **running** before browser verification. The browser subagent gets `ERR_CONNECTION_REFUSED` if the server is not started first. Always start the server BEFORE invoking the browser subagent.

## Steps

### 1. Start the Flask server in the background
// turbo
Run the following command (it will run in the background):
```
python wsgi.py
```
Wait for the command to show `* Running on http://127.0.0.1:8080` in its output before proceeding.
Check with command_status and wait until you see the `Running on` line.

### 2. Confirm the server is ready
// turbo
Check command status of the server start command. Look for output containing: `Running on http://127.0.0.1:8080`

### 3. Run browser verification
Now invoke the `browser_subagent` tool with your verification task.

**Key facts for browser tasks:**
- Login URL: `http://127.0.0.1:8080/auth/login`
- Credentials: username=`admin`, password=`admin`
- Patient list: `http://127.0.0.1:8080/patients/`
- Do NOT use `/home` or `/login` — use `http://127.0.0.1:8080/` or `/auth/login`
- **CSS changes require a hard-refresh:** tell the subagent to navigate fresh or press `Ctrl+Shift+R`

### 4. View screenshots yourself (MANDATORY — Definition of Done)
After the browser subagent finishes, do NOT trust its text description alone.
Use `find_by_name` to find any saved screenshots, then `view_file` to inspect them.

```
find_by_name: *.png in .system_generated/click_feedback/
```

If no screenshots were taken, the verification did not happen. Take them yourself.

### 5. After verification, stop the server (optional)
If needed, terminate the background command that was started in step 1.

## Notes
- The app uses port **8080** exclusively (not 5000, 8000, or 3000)
- Entry point is `wsgi.py` (not `app.py` or `run.py`)
- Failed logins trigger rate limiting (5 per 15 min) — always use `admin`/`admin`
