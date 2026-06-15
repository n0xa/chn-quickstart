#!/usr/bin/env python3
"""
hpfeeds_proxy.py — Forward live hpfeeds events from production into dev.

Subscribes to all channels on the production broker using the seckc-community
read-only account and republishes each message into the local dev broker.
Events will appear in mnemosyne under the 'hpfeeds-proxy' ident.

Provisions the local hpfeeds-proxy broker user on first run if it doesn't exist.

Usage:
    python3 scripts/hpfeeds_proxy.py
"""

import asyncio
import json
import logging
import subprocess
import sys

sys.path.insert(0, '/home/axon/source/chnserver/hpfeeds3')
from hpfeeds.asyncio.client import ClientSession

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('hpfeeds-proxy')

PROD = dict(
    host='mhn.h-i-r.net',
    port=10000,
    ident='seckc-community',
    secret='fk6QgrnyvwbWSxCIwL5SIc2oARC4DXx46',
)

DEV = dict(
    host='127.0.0.1',
    port=10000,
    ident='hpfeeds-proxy',
    secret='bZHjDk8top0IEvySpt1lkmQWsbUc8aaglDmkPUHIAFo',
)

CHANNELS = [
    'amun.events', 'conpot.events', 'thug.events', 'beeswarm.hive',
    'dionaea.capture', 'dionaea.connections', 'thug.files', 'beeswarm.feeder',
    'cuckoo.analysis', 'kippo.sessions', 'cowrie.sessions', 'glastopf.events',
    'glastopf.files', 'mwbinary.dionaea.sensorunique', 'snort.alerts',
    'wordpot.events', 'p0f.events', 'suricata.events', 'shockpot.events',
    'elastichoney.events', 'rdphoney.sessions', 'uhp.events', 'elasticpot.events',
    'spylex.events', 'big-hp.events', 'ssh-auth-logger.events', 'honeydb-agent.events',
]

MONGO_CONTAINER = 'chn-quickstart-mongodb-1'


def mongosh(js):
    result = subprocess.run(
        ['docker', 'exec', MONGO_CONTAINER, 'mongosh', 'hpfeeds', '--quiet', '--eval', js],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f'mongosh failed: {result.stderr.strip()}')
    return result.stdout.strip()


def provision_dev_user():
    existing = mongosh(
        f"JSON.stringify(db.auth_key.findOne({{identifier: '{DEV['ident']}'}}," +
        " {identifier: 1, _id: 0}))"
    )
    if DEV['ident'] in existing:
        log.info('Dev broker user %r already exists, skipping provisioning', DEV['ident'])
        return

    log.info('Provisioning dev broker user %r', DEV['ident'])
    channels_js = json.dumps(CHANNELS)
    mongosh(f"""
        db.auth_key.insertOne({{
            identifier: '{DEV['ident']}',
            secret: '{DEV['secret']}',
            owner: 'proxy',
            publish: {channels_js},
            subscribe: []
        }})
    """)
    log.info('Dev broker user %r provisioned', DEV['ident'])


async def main():
    provision_dev_user()

    log.info('Connecting to prod broker at %s:%d', PROD['host'], PROD['port'])
    log.info('Connecting to dev broker at %s:%d', DEV['host'], DEV['port'])

    async with ClientSession(**PROD) as prod:
        async with ClientSession(**DEV) as dev:
            log.info('Connected to both brokers, subscribing to %d channels', len(CHANNELS))
            for chan in CHANNELS:
                prod.subscribe(chan)

            async for ident, chan, payload in prod:
                log.info('<- [%s] from %s (%d bytes)', chan, ident, len(payload))
                dev.publish(chan, payload)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info('Stopped.')
