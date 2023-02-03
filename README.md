# gpustats

Periodically scrape ```nvidia-smi``` and store detailed info to local sqlite3 database.

## How to run

The script maintains its lock, so it is safe to run it periodically.
If other instance is running, the script finish instantly.

For quick run without any hassle with systemd, let's add this into crontab:
```
0 *  * * * cd <gpustats workdir>/ && ./gpustats.py
```

Alternatively, you can use gpustats.service as systemd launcher.
That will require additional system configuration like creating gpustats user,
creating working directory for lock and database etc, as this isn't handled by
the script.
