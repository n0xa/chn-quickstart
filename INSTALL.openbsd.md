# CHN Stack -- Native OpenBSD Install Guide

Tested on OpenBSD 7.9 (amd64). All services run as the `chn` user under `/opt/chnserver`.
No Docker. Process management via rc.d.

## Architecture

```
[Honeypots] --> [hpfeeds broker :10000]
                        |
                [hpfeeds_bridge.py]   <-- subscribes, inserts to MongoDB
                        |
               [MongoDB :27017 (mnemosyne db)]
                        |
                  [mnemosyne] <-- normalizer greenlet only (--no_feedpuller)
                        |
               [MongoDB :27017 (mnemosyne db)]
                        |
          +-------------+-------------+
          |                           |
   [CHN-Server :5001]     [seckc-mhn-dashboard-api :5000]
          |                           |
          +-------------+-------------+
                        |
                  [nginx :80]
```

**Why hpfeeds_bridge.py?** `gevent.monkey.patch_all()` in mnemosyne replaces
asyncio's selector with GeventSelector, which does not work for TCP connections
on OpenBSD. The bridge is a standalone asyncio script (no gevent) that fills
the same role as mnemosyne's built-in feedpuller.

## 1. System packages

```sh
doas pkg_add python3 mongodb redis nginx rsync git \
    libmagic libmaxminddb py3-bcrypt py3-cryptography
```

OpenBSD ships Python 3.13. bcrypt and cryptography must come from packages
(no PyPI wheels available for OpenBSD).

## 2. System user and layout

```sh
doas useradd -d /opt/chnserver -s /sbin/nologin -c "CHN services" chn
doas mkdir -p /opt/chnserver
doas chown chn:chn /opt/chnserver
```

## 3. Clone repos

```sh
doas -u chn sh
cd /opt/chnserver
git clone https://github.com/ax0n-pr1me/hpfeeds3
git clone https://github.com/ax0n-pr1me/mnemosyne
git clone https://github.com/ax0n-pr1me/CHN-Server
git clone https://github.com/ax0n-pr1me/seckc-mhn-dashboard-api
exit
```

Or rsync from an existing deployment:
```sh
rsync -av --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' \
    source_host:/opt/chnserver/ /opt/chnserver/
```

## 4. hpfeeds3

```sh
doas -u chn sh -c '
cd /opt/chnserver/hpfeeds3
python3 -m venv venv
. venv/bin/activate
pip install -e .
'
```

Install rc.d script:
```sh
doas cp /opt/chnserver/hpfeeds3/openbsd/hpfeeds_broker /etc/rc.d/
doas chmod 555 /etc/rc.d/hpfeeds_broker
```

## 5. MongoDB setup

```sh
doas rcctl enable mongod
doas rcctl start mongod
```

Raise IPC semaphore limits (two uwsgi instances each need ~8 semaphores):
```sh
doas sysctl kern.seminfo.semmni=20
doas sysctl kern.seminfo.semmns=120
```

Persist in `/etc/sysctl.conf`:
```
kern.seminfo.semmni=20
kern.seminfo.semmns=120
```

Provision hpfeeds auth keys (substitute your own secrets):
```sh
mongo hpfeeds --eval '
db.auth_key.replaceOne(
  {identifier: "mnemosyne-XXXXXXXX"},
  {identifier: "mnemosyne-XXXXXXXX", owner: "chn", secret: "YOUR_SECRET_HERE",
   publish: [], subscribe: ["dionaea.capture","dionaea.connections",
   "cowrie.sessions","cowrie.commands","cowrie.logins","kippo.sessions",
   "conpot.events","glastopf.events","glastopf.files",
   "thug.events","thug.files","snort.alerts"]},
  {upsert: true}
)'
```

Then start the broker and verify it listens:
```sh
doas rcctl enable hpfeeds_broker
doas rcctl start hpfeeds_broker
nc -z 127.0.0.1 10000 && echo "broker up"
```

## 6. mnemosyne

```sh
doas -u chn sh -c '
cd /opt/chnserver/mnemosyne
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
mkdir -p logs
'
```

Write `/opt/chnserver/mnemosyne/mnemosyne.cfg` (substitute real ident/secret):
```ini
[mongodb]
mongo_host = localhost
mongo_port = 27017
database = mnemosyne
mongo_indexttl = 86400

[file_log]
enabled = true
file = ./logs/mnemosyne.log

[loggly_log]
enabled = false

[hpfriends]
hp_host = localhost
hp_port = 10000
owner = chn
ident = mnemosyne-XXXXXXXX
secret = YOUR_SECRET_HERE
channels = dionaea.capture,dionaea.connections,cowrie.sessions,cowrie.commands,cowrie.logins,kippo.sessions,conpot.events,glastopf.events,glastopf.files,thug.events,thug.files,snort.alerts

[normalizer]
ignore_rfc1918 = false
```

Install rc.d scripts and wrapper:
```sh
doas cp /opt/chnserver/mnemosyne/mnemosyne_wrapper.sh /opt/chnserver/mnemosyne/
doas cp /opt/chnserver/mnemosyne/hpfeeds_bridge_wrapper.sh /opt/chnserver/mnemosyne/
doas chmod 755 /opt/chnserver/mnemosyne/mnemosyne_wrapper.sh
doas chmod 755 /opt/chnserver/mnemosyne/hpfeeds_bridge_wrapper.sh
doas chown chn:chn /opt/chnserver/mnemosyne/mnemosyne_wrapper.sh
doas chown chn:chn /opt/chnserver/mnemosyne/hpfeeds_bridge_wrapper.sh

doas cp /opt/chnserver/mnemosyne/openbsd/mnemosyne /etc/rc.d/
doas cp /opt/chnserver/mnemosyne/openbsd/hpfeeds_bridge /etc/rc.d/
doas chmod 555 /etc/rc.d/mnemosyne /etc/rc.d/hpfeeds_bridge

doas touch /var/log/hpfeeds_bridge.log
doas chown chn:chn /var/log/hpfeeds_bridge.log
```

Enable and start:
```sh
doas rcctl enable mnemosyne hpfeeds_bridge
doas rcctl start mnemosyne
doas rcctl start hpfeeds_bridge
```

Verify bridge connected:
```sh
doas tail /var/log/hpfeeds_bridge.log
# should show: Connected, subscribed to 12 channels
```

## 7. Redis

```sh
doas rcctl enable redis
doas rcctl start redis
```

## 8. CHN-Server

```sh
# CHN-Server venv needs system bcrypt/cryptography packages
doas -u chn sh -c '
cd /opt/chnserver/CHN-Server
python3 -m venv --system-site-packages venv
. venv/bin/activate
pip install -r requirements.txt
pip install uwsgi
'

# Generate config and initialize database
doas -u chn sh -c '
cd /opt/chnserver/CHN-Server
. venv/bin/activate
SECRET_KEY=$(openssl rand -hex 32)
python3 generateconfig.py unattended \
    --server-base-url http://YOUR_HOST_IP \
    --secret-key "$SECRET_KEY" \
    --redis-url redis://localhost:6379 \
    --mongo-host localhost
python3 initdatabase.py
mkdir -p logs
'
```

Create admin user via flask shell or the API, or use the default `admin@localhost` / `chndev` if initdatabase.py sets it.

Install rc.d script:
```sh
doas cp /opt/chnserver/CHN-Server/openbsd/chn /etc/rc.d/
doas chmod 555 /etc/rc.d/chn
doas rcctl enable chn
doas rcctl start chn
```

## 9. seckc-mhn-dashboard-api

```sh
doas -u chn sh -c '
cd /opt/chnserver/seckc-mhn-dashboard-api
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
pip install uwsgi
mkdir -p logs
'
```

Write `/opt/chnserver/seckc-mhn-dashboard-api/seckc_mhn_api.env`:
```
HPFEEDS_HOST=localhost
HPFEEDS_PORT=10000
HPFEEDS_USER=mnemosyne-XXXXXXXX
HPFEEDS_SECRET=YOUR_SECRET_HERE
HPFEEDS_CHANNELS=cowrie.sessions,cowrie.commands,cowrie.logins,dionaea.connections,conpot.events
SOCKETIO_HOST=127.0.0.1
SOCKETIO_PORT=5000
MONGODB_HOST=localhost
MONGODB_PORT=27017
MONGO_DB=mnemosyne
```

Install rc.d script:
```sh
doas cp /opt/chnserver/seckc-mhn-dashboard-api/openbsd/seckc_mhn_api /etc/rc.d/
doas chmod 555 /etc/rc.d/seckc_mhn_api
doas rcctl enable seckc_mhn_api
doas rcctl start seckc_mhn_api
```

## 10. nginx

Install `/etc/nginx/conf.d/chn.conf`:
```nginx
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 32m;
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;

    location /static/ {
        alias /opt/chnserver/CHN-Server/mhn/static/;
    }

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

The `default_server` directive is required -- without it, nginx's built-in
`server_name localhost` block intercepts requests before your config.

Enable and start:
```sh
doas rcctl enable nginx
doas rcctl start nginx
```

## 11. Verify

```sh
# All services green
for s in mongod redis hpfeeds_broker hpfeeds_bridge mnemosyne chn seckc_mhn_api nginx; do
    printf '%-20s' "$s"; doas rcctl check "$s"
done

# CHN-Server responding
curl -s -o /dev/null -w '%{http_code}' http://localhost/

# mnemosyne ingesting
mongo mnemosyne --quiet --eval 'print("sessions:", db.session.count())'

# hpfeeds bridge log
doas tail /var/log/hpfeeds_bridge.log
```

## Service start order on boot

rc.d handles ordering via `rc_pre` checks. If a service fails to start at boot
because a dependency isn't ready, `rcctl start <service>` after mongod is up
will succeed. For a completely clean boot order, `/etc/rc.conf.local` entries
are sufficient -- all services are enabled via `rcctl enable`.

## Gotchas

- **bcrypt / cryptography**: must come from `pkg_add py3-bcrypt py3-cryptography`,
  not pip. CHN-Server venv requires `--system-site-packages` to reach them.
- **libmagic**: `pkg_add libmagic` -- it is a separate package from `file`.
- **uwsgi**: not available as an OpenBSD package; compile from pip (`pip install uwsgi`).
  Builds cleanly with clang on 7.9.
- **hpfeeds auth_key schema**: the broker queries by `identifier`, not `ident`.
  Fields: `identifier`, `owner`, `secret`, `publish` (list), `subscribe` (list).
- **nginx default_server**: required when multiple server blocks listen on port 80.
- **gevent + asyncio on OpenBSD**: GeventSelector does not support TCP. Run
  mnemosyne with `--no_feedpuller` and use `hpfeeds_bridge.py` instead.
- **hpfeeds_bridge rc.d**: uses a custom `rc_start`/`rc_check`/`rc_stop` with
  a PID file (`/var/run/hpfeeds_bridge.pid`) because the standard `su -fl`
  launch in rc.subr has a timing race on this service.
- **IPC semaphores**: default `semmni=10` is too low for two uwsgi instances.
  Raise to 20 and persist in `/etc/sysctl.conf`.
- **OpenBSD sed**: does not interpret `\n` in replacement strings. Use Python
  for multi-line file edits.
