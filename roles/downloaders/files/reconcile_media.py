#!/usr/bin/env python3
"""Reconcile klaxon's media services using their APIs; never search/grab media.

Run as root. Credentials stay in memory; changed objects are backed up root-only.
Container addresses are discovered at runtime, while saved links use Docker DNS.
"""
import copy
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

os.umask(0o077)
CHANGES = []
CONFIG_ROOT = Path(os.environ.get('MEDIA_CONFIG_ROOT', '/data/docker'))
BACKUP = Path('/data/docker/connection-backups') / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(label, value):
    BACKUP.mkdir(parents=True, exist_ok=True, mode=0o700)
    (BACKUP / (label + '.json')).write_text(json.dumps(value, indent=2))


def changed(label):
    CHANGES.append(label)
    print('Changed: ' + label, flush=True)


def address(name):
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    return obj['NetworkSettings']['Networks']['downloaders']['IPAddress']


class API:
    def __init__(self, name, port, version=3):
        self.name = name
        self.base = f'http://{address(name)}:{port}/api/v{version}/'
        if name == 'seerr':
            self.key = json.loads((CONFIG_ROOT / 'seerr/config/settings.json').read_text())['main']['apiKey']
        else:
            self.key = ET.parse(CONFIG_ROOT / name / 'config/config.xml').findtext('ApiKey')
        for attempt in range(30):
            try:
                self.request('status' if name == 'seerr' else 'system/status')
                break
            except (RuntimeError, urllib.error.URLError, TimeoutError):
                if attempt == 29:
                    raise RuntimeError(name + ' did not become ready') from None
                time.sleep(2)

    def request(self, path, data=None, method=None):
        request = urllib.request.Request(
            self.base + path,
            headers={'X-Api-Key': self.key, 'Content-Type': 'application/json'},
            data=None if data is None else json.dumps(data).encode(), method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            # Bodies/URLs can contain credentials; deliberately do not print them.
            raise RuntimeError(f'{self.name}: {path.split("?")[0]} returned HTTP {error.code}') from None

    def update(self, path, old, new, label):
        if old != new:
            backup(label, old)
            self.request(path, new, 'PUT')
            changed(label)


def fields(obj, values):
    result = copy.deepcopy(obj)
    for field in result['fields']:
        if field['name'] in values:
            field['value'] = values[field['name']]
    return result


def main():
    sonarr, radarr, prowlarr, seerr = API('sonarr', 8989), API('radarr', 7878), API('prowlarr', 9696, 1), API('seerr', 5055, 1)
    sab_key = re.search(r'^api_key\s*=\s*(\S+)', (CONFIG_ROOT / 'sabnzbd/config/sabnzbd.ini').read_text(), re.M).group(1)

    def sab(**args):
        args.update(apikey=sab_key, output='json')
        with urllib.request.urlopen('http://' + address('sabnzbd') + ':8080/api', data=urllib.parse.urlencode(args).encode(), timeout=30) as response:
            return json.load(response)

    allowed = sab(mode='get_config', section='misc', keyword='host_whitelist')['config']['misc']['host_whitelist']
    if 'sabnzbd' not in allowed:
        backup('sab-host-whitelist', allowed)
        result = sab(mode='set_config', section='misc', keyword='host_whitelist', value=','.join(allowed + ['sabnzbd']))
        assert 'sabnzbd' in result['config']['misc']['host_whitelist']
        changed('sab-host-whitelist')
    # Completed output still goes to one HDD. Avoid multiple direct unpackers
    # competing for that disk while Plex reads it; retain cache/network limits.
    unpackers = sab(mode='get_config', section='misc', keyword='direct_unpack_threads')['config']['misc']['direct_unpack_threads']
    if int(unpackers) != 1:
        backup('sab-direct-unpack-threads', unpackers)
        result = sab(mode='set_config', section='misc', keyword='direct_unpack_threads', value=1)
        assert int(result['config']['misc']['direct_unpack_threads']) == 1
        changed('sab-direct-unpack-threads')
    for api in [sonarr, radarr]:
        for old in api.request('downloadclient'):
            if old['implementation'] == 'Sabnzbd':
                new = fields(old, {'host': 'sabnzbd', 'port': 8080, 'useSsl': False})
                # Keep unchanged keys opaque; use SAB's actual key only for a connection change.
                if old != new:
                    new = fields(new, {'apiKey': sab_key})
                    api.request('downloadclient/test', new)
                    api.update('downloadclient/' + str(old['id']), old, new, api.name + '-sab')

    apps = {'Sonarr': 'http://sonarr:8989', 'Radarr': 'http://radarr:7878', 'Readarr': 'http://readarr:8787'}
    for old in prowlarr.request('applications'):
        if old['implementation'] in apps:
            new = fields(old, {'baseUrl': apps[old['implementation']], 'prowlarrUrl': 'http://prowlarr:9696'})
            if old != new:
                prowlarr.request('applications/test', new)
                prowlarr.update('applications/' + str(old['id']), old, new, 'prowlarr-' + old['implementation'].lower())

    # Sync only when managed URLs changed or an Arr still has public Prowlarr URLs.
    needs_sync = any(label.startswith('prowlarr-') for label in CHANGES)
    for api in [sonarr, radarr]:
        for indexer in api.request('indexer'):
            if '(Prowlarr)' in indexer['name']:
                needs_sync |= any(f['name'] == 'baseUrl' and not f.get('value', '').startswith('http://prowlarr:9696/') for f in indexer['fields'])
    if needs_sync:
        command = prowlarr.request('command', {'name': 'ApplicationIndexerSync'})
        for _ in range(60):
            state = prowlarr.request('command/' + str(command['id']))['status']
            if state == 'completed':
                break
            if state in ['failed', 'aborted']:
                raise RuntimeError('Prowlarr application sync failed')
            time.sleep(1)
        else:
            raise RuntimeError('Prowlarr sync did not finish within 60 seconds')

    # Test real indexers before retiring legacy unmanaged Radarr entries.
    for api in [sonarr, radarr]:
        managed = [x for x in api.request('indexer') if '(Prowlarr)' in x['name'] and x.get('enableRss')]
        if not managed:
            raise RuntimeError(api.name + ': no enabled Prowlarr indexers')
        for indexer in managed:
            api.request('indexer/test', indexer)
            print('Verified: ' + api.name + ' / ' + indexer['name'], flush=True)
    for old in radarr.request('indexer'):
        if '(Prowlarr)' not in old['name']:
            new = dict(old, enableRss=False, enableAutomaticSearch=False, enableInteractiveSearch=False)
            radarr.update('indexer/' + str(old['id']), old, new, 'radarr-legacy-indexer-' + str(old['id']))

    # Profile 1 was the site's broad Any profile. Preserve the dedicated Anime profile.
    profiles = sonarr.request('qualityprofile')
    old = next(p for p in profiles if p['id'] == 1)
    if old['name'] not in ['Any', 'Standard TV (1080p)']:
        raise RuntimeError('Profile 1 was customized; refusing to overwrite it')
    new = copy.deepcopy(old)
    new.update(name='Standard TV (1080p)', upgradeAllowed=True, cutoff=1003, minFormatScore=0, cutoffFormatScore=0)
    allowed_qualities = {1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 22}
    for item in new['items']:
        if item.get('items'):
            for child in item['items']:
                child['allowed'] = child['quality']['id'] in allowed_qualities
            item['allowed'] = any(child['allowed'] for child in item['items'])
        else:
            item['allowed'] = item['quality']['id'] in allowed_qualities
    assert any(x.get('id') == 1003 and x.get('name') == 'WEB 1080p' for x in new['items'])
    for item in new['formatItems']:
        if item['name'].lower().startswith('anime'):
            item['score'] = 0
    sonarr.update('qualityprofile/1', old, new, 'standard-tv-profile')
    for old in profiles:
        if old['id'] == 1 or 'anime' in old['name'].lower():
            continue
        new = copy.deepcopy(old)
        for item in new['formatItems']:
            if item['name'].lower().startswith('anime'):
                item['score'] = 0
        sonarr.update('qualityprofile/' + str(old['id']), old, new, 'regular-profile-' + str(old['id']))

    for kind, port in [('sonarr', 8989), ('radarr', 7878)]:
        for old in seerr.request('settings/' + kind):
            new = dict(old, hostname=kind, port=port, useSsl=False)
            if kind == 'sonarr' and new.get('isDefault') and not new.get('is4k'):
                new.update(activeProfileId=1, activeProfileName='Standard TV (1080p)')
            if new != old:
                backup('seerr-' + kind + '-' + str(old['id']), old)
                new.pop('id')
                seerr.request('settings/' + kind + '/test', new)
                seerr.request('settings/' + kind + '/' + str(old['id']), new, 'PUT')
                changed('seerr-' + kind)
    for job in seerr.request('settings/jobs'):
        if job['id'] == 'plex-recently-added-scan' and job['cronSchedule'] != '0 */2 * * * *':
            backup('seerr-recently-added-job', job)
            seerr.request('settings/jobs/plex-recently-added-scan/schedule', {'schedule': '0 */2 * * * *'})
            changed('seerr-recently-added-job')
    print(json.dumps({'changed': bool(CHANGES), 'changes': CHANGES}))


def plex_settings():
    token = ET.parse(CONFIG_ROOT / 'plex/config/Library/Application Support/Plex Media Server/Preferences.xml').getroot().get('PlexOnlineToken')
    headers = {'X-Plex-Token': token}
    url = 'http://127.0.0.1:32400/:/prefs'
    for attempt in range(30):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
                prefs = {x.get('id'): x.get('value') for x in ET.fromstring(response.read())}
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 29:
                raise RuntimeError('Plex did not become ready') from None
            time.sleep(2)
    desired = {'GenerateIntroMarkerBehavior': 'scheduled', 'GenerateCreditsMarkerBehavior': 'scheduled'}
    delta = {k: v for k, v in desired.items() if prefs.get(k) != v}
    if delta:
        backup('plex-marker-schedule', {k: prefs.get(k) for k in delta})
        with urllib.request.urlopen(urllib.request.Request(url + '?' + urllib.parse.urlencode(delta), headers=headers, method='PUT'), timeout=30):
            pass
        changed('plex-marker-schedule')
    print(json.dumps({'changed': bool(CHANGES), 'changes': CHANGES}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--plex-only']:
        plex_settings()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit('Usage: reconcile-media [--plex-only]')
