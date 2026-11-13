# FTPS test server (vsftpd on test-jeedom)

**TLDR:** epic 18 develops and validates against vsftpd running on test-jeedom itself: explicit FTPS (FTPES) on port 21, self-signed certificate, account `siaftps` locked to `upload/`. The daemon connects over loopback, so no firewall is involved. `scripts/ftps_probe.py` checks it end to end.

## Settled choices (ticket 18.1, revised 2026-11-09)

| Choice | Value | Why |
|--------|-------|-----|
| Server | vsftpd on test-jeedom | The Synology is unreachable from the test VLAN (.40.x) and the firewall stays as is |
| TLS mode | Explicit (FTPES), port 21 | Plugin scope is explicit TLS; vsftpd could also do implicit (990) if ever needed |
| Certificate | Self-signed first | Exercises the pinned-fingerprint path; the CA-signed case is tested later (18.9) |
| Account | `siaftps`, chrooted, writes in `upload/` only | Dedicated test account; no password in the repository |

## Install (human step, needs root on test-jeedom)

```
apt install vsftpd
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/vsftpd.key -out /etc/ssl/certs/vsftpd.pem -subj "/CN=test-jeedom.lehoux.net" -addext "subjectAltName=DNS:test-jeedom.lehoux.net"
chmod 600 /etc/ssl/private/vsftpd.key
echo /usr/sbin/nologin >> /etc/shells
useradd -d /srv/ftps/siaftps -s /usr/sbin/nologin siaftps
passwd siaftps
mkdir -p /srv/ftps/siaftps/upload
chown root:root /srv/ftps/siaftps
chown siaftps: /srv/ftps/siaftps/upload
echo siaftps > /etc/vsftpd.userlist
```

The chroot root `/srv/ftps/siaftps` must not be writable by the account (vsftpd refuses otherwise), hence the `upload/` subfolder. `nologin` must be in `/etc/shells` or the PAM shell check rejects the login.

## `/etc/vsftpd.conf`

```
listen=YES
listen_ipv6=NO
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=022
chroot_local_user=YES
userlist_enable=YES
userlist_deny=NO
userlist_file=/etc/vsftpd.userlist
xferlog_enable=YES

ssl_enable=YES
rsa_cert_file=/etc/ssl/certs/vsftpd.pem
rsa_private_key_file=/etc/ssl/private/vsftpd.key
force_local_logins_ssl=YES
force_local_data_ssl=YES
ssl_sslv2=NO
ssl_sslv3=NO
ssl_tlsv1=NO
ssl_ciphers=HIGH
# Python's ftplib does not reuse the control-channel TLS session on data connections.
# Without this line login works and the first transfer fails.
require_ssl_reuse=NO

pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100
```

Then `systemctl restart vsftpd`. Passive mode needs no `pasv_address` while the client reaches the server by the address it connected to (loopback or the host's own IP).

## Run the probe

Read the certificate fingerprint on the server:

```
openssl x509 -in /etc/ssl/certs/vsftpd.pem -noout -fingerprint -sha256
```

Then, from test-jeedom, pin it:

```
FTPS_PASSWORD='...' python3 scripts/ftps_probe.py --host test-jeedom.lehoux.net --user siaftps --folder upload --fingerprint <sha256>
```

`--insecure` prints the fingerprint the server presents without trusting it, if you prefer to read it from the probe.

Expected: a PASS line per step (connect, tls, login, data-protection, cwd, upload, list, download, delete), plus a `fingerprint` PASS line with `--fingerprint` (with `--insecure` only an `INFO certificate sha256` line), then `RESULT PASS`, and an empty `upload/` afterwards. Without `--fingerprint` or `--insecure`, a self-signed server fails on certificate verification, which is the intended default.

The password is read from `FTPS_PASSWORD` only and is never printed.

## Remote file layout (ticket 18.13, replaces the 18.8 folders)

Files go flat at the root of the configured FTPS folder (`upload/` on the test server), named as the receiver expects `{UID}_{zone}_{timestamp}_{image}`:

| Part | Rule | Example |
|------|------|---------|
| Folder | none: the configured folder itself, no subfolder is created | `upload/` |
| File | `<account>_<zone number, 2 digits>_<Unix epoch seconds>_0001.<jpg or mp4>` | `12345678_01_1675938881_0001.jpg` |

- The clip of the same alarm sits beside the snapshot with the same name and the `.mp4` extension (one epoch shared by both media).
- The epoch is the daemon's time when the alarm is handled; it is timezone-independent.
- The account goes through `safe_name_part()` (anything outside `A-Za-z0-9._-` becomes `_`); an empty or dots-only account becomes `noaccount`. A zone of three digits is not truncated (`..._123_...`); an absent zone number gives `00`.
- The image part is the constant `0001` (`IMAGE_NUMBER`), the one place to change for a future series feature.
- Same zone in the same second (two events): same name, the later file overwrites the earlier. Accepted by the user.
- To test in the field: the `0001` clip (`.mp4`) is not yet confirmed to be accepted by the receiver.
- Deferred, not in this version: retention, cleanup or quota on the server (files are never deleted by the plugin), and a configurable layout.

## Not covered

A loopback server proves the protocol and the code, not the network. Timeouts and unreachable servers (18.6) are simulated by stopping or throttling vsftpd; the field run against a separate FTPS server is 18.9.
