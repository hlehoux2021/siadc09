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

## Not covered

A loopback server proves the protocol and the code, not the network. Timeouts and unreachable servers (18.6) are simulated by stopping or throttling vsftpd; the field run against a separate FTPS server is 18.9.
