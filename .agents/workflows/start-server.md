---
description: Start the Flask development server on port 8080
---
This workflow provides the safest and most reliable way to start the local Flask server for browser testing, bypassing PowerShell script execution issues.

// turbo-all
1. Start the server using Python directly, which avoids `.bat` execution policy errors in PowerShell. Do not forget to wait for it before moving on.
```bash
python wsgi.py
```

2. When you are done testing in the browser, remember to use the `send_command_input` tool with `Terminate: true` on the command ID returned by step 1 so the port is freed for the next task.
