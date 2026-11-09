# FTPS test server (Synology)

**TLDR:** epic 18 develops and validates against the Synology at `starfire-internal.lehoux.net` (192.168.100.9): explicit FTPS (FTPES) on port 21, DSM's self-signed certificate, shared folder `ftp-server`. `scripts/ftps_probe.py` checks it end to end.

## Settled choices (ticket 18.1)

| Choice | Value | Why |
|--------|-------|-----|
| TLS mode | Explicit (FTPES), port 21 | What DSM's FTP service offers; implicit (990) is not covered |
| Certificate | DSM self-signed first | Exercises the pinned-fingerprint path; the CA-signed case is tested later (18.9) |
| Host | `starfire-internal.lehoux.net` / 192.168.100.9 | LAN only, no port forwarding |
| Folder | Shared folder `ftp-server` | Test account is limited to it |

## Synology setup (human step)

1. Control Panel > File Services > FTP: enable **FTP SSL/TLS encryption (FTPS)**; leave plain FTP off.
2. Create a dedicated account with access to `ftp-server` only, FTP permission on, no other service.
3. Note the password in your password manager; never in the repository.

## Run the probe

Discover the certificate fingerprint (no verification, nothing but the fingerprint is trusted from this run):

```
FTPS_PASSWORD='...' python3 scripts/ftps_probe.py --host starfire-internal.lehoux.net --user <account> --folder ftp-server --insecure
```

Then pin it, from the machine that hosts test-jeedom:

```
FTPS_PASSWORD='...' python3 scripts/ftps_probe.py --host starfire-internal.lehoux.net --user <account> --folder ftp-server --fingerprint <sha256>
```

Expected: a PASS line per step (connect, tls, login, data-protection, cwd, upload, list, download, delete), plus a `fingerprint` PASS line with `--fingerprint` (with `--insecure` only an `INFO certificate sha256` line), then `RESULT PASS`, and an empty folder afterwards. Without `--fingerprint` or `--insecure`, a self-signed server fails on certificate verification, which is the intended default.

The password is read from `FTPS_PASSWORD` only and is never printed.
