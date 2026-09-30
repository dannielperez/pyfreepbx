#!/usr/bin/env python
"""Passive PBX media evidence. Python 2.7/3 compatible; never stores RTP payloads.

SIP answers alone are insufficient: a live Asterisk bridge must independently
associate two unique PJSIP endpoints. Missing/ambiguous/late evidence is unknown.
"""
from __future__ import print_function
import collections
import hashlib
import json
import os
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
try:
    import Queue as queue
except ImportError:
    import queue

from queue_stability import summarize_queue_calls, MAX_TEXT

STATIC_VOICE = set([0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18])

def command(args, seconds=4):
    return subprocess.check_output(['timeout', str(seconds)] + args).decode('utf8', 'replace')

def ipv4_udp(data, link):
    offset = {1: 14, 113: 16, 276: 20, 101: 0, 12: 0}.get(link)
    if offset is None:
        raise ValueError('Unsupported capture interface')
    d = bytearray(data[offset:])
    if len(d) < 28 or d[0] >> 4 != 4 or d[9] != 17:
        return None
    if struct.unpack('!H', bytes(d[6:8]))[0] & 16383:
        return None
    h = (d[0] & 15) * 4
    if len(d) < h + 8:
        return None
    sp, dp, length = struct.unpack('!HHH', bytes(d[h:h+6]))
    return ('.'.join(str(x) for x in d[12:16]), sp,
            '.'.join(str(x) for x in d[16:20]), dp, bytes(d[h+8:h+length]))

def audio_section(sdp):
    """Select one active audio section; video direction/codecs do not apply.

    Session direction is inherited unless audio explicitly overrides it. Multiple
    audio streams remain unsupported rather than being correlated ambiguously.
    """
    body = sdp.split('\r\n\r\n', 1)[-1]
    parts = re.split(r'(?m)(?=^m=)', body)
    session = parts[0] if not parts[0].startswith('m=') else ''
    audio = [part for part in parts if part.startswith('m=audio ')]
    if len(audio) != 1:
        return None
    section = audio[0]
    directions = re.findall(r'(?m)^a=(sendrecv|sendonly|recvonly|inactive)\r?$', section)
    if not directions:
        directions = re.findall(r'(?m)^a=(sendrecv|sendonly|recvonly|inactive)\r?$', session)
    if len(directions) > 1 or (directions and directions[0] != 'sendrecv'):
        return None
    if re.search(r'(?m)^c=IN IP4 0\.0\.0\.0\r?$', section or session):
        return None
    if not re.search(r'(?m)^c=', section) and re.search(r'(?m)^c=IN IP4 0\.0\.0\.0\r?$', session):
        return None
    return section

class Evidence(object):
    def __init__(self, addresses, expected):
        self.addresses = set(addresses)
        self.expected = set(expected)
        self.dialogs = {}
        self.pairs = {}
        self.completed = []
        self.complete = False
        self.capture_after = 0
        self.lock = threading.RLock()

    def capture_health(self, healthy, observed_at):
        """Discard uncertain dialogs; never rehabilitate a window with lost SIP/RTP."""
        with self.lock:
            self.complete = healthy
            if not healthy:
                self.capture_after = observed_at
                self.dialogs.clear()
                self.pairs.clear()
                self.completed = []

    def sip(self, at, src, sp, dst, dp, payload):
        s = payload.decode('latin1')
        def field(name):
            m = re.search(r'(?im)^' + name + r':\s*(.*)', s)
            return m.group(1).strip() if m else ''
        cid = field('Call-ID')
        if not cid:
            return
        first = s.splitlines()[0]
        if first.startswith('INVITE '):
            m = re.search(r'sip:([0-9]+)@', field('From' if dst in self.addresses else 'To'))
            if not m:
                return
            if cid not in self.dialogs:
                if len(self.dialogs) >= 500:
                    self.complete = False
                    return
                self.dialogs[cid] = {'ext': m.group(1), 'start': at, 'seq': field('CSeq'),
                    'answered': False, 'ack': False, 'valid': True, 'counts': [0, 0], 'seen': set(),
                    'voice': set(), 'nonvoice': set(), 'control_rx': 0, 'port': None, 'last': at}
            elif self.dialogs[cid]['seq'] != field('CSeq'):
                # Authentication challenge retries precede the answer.
                if self.dialogs[cid]['answered']:
                    self.dialogs[cid]['valid'] = False
                else:
                    self.dialogs[cid]['seq'] = field('CSeq')
        d = self.dialogs.get(cid)
        if not d:
            return
        d['last'] = at
        length = field('Content-Length')
        if length.isdigit() and len(s.split('\r\n\r\n',1)[-1]) < int(length):
            d['valid'] = False
            return
        if first.startswith('BYE ') or first.startswith('CANCEL '):
            self.close(cid, at)
            return
        if first.startswith('ACK '):
            d['ack'] = True
        if first.startswith('SIP/2.0 200') and 'INVITE' in field('CSeq'):
            d['answered'] = True
        if 'INVITE' not in field('CSeq') or not (first.startswith('INVITE ') or first.startswith('SIP/2.0 200')):
            return
        audio = audio_section(s)
        media = re.search(r'(?m)^m=audio (\d+) RTP/AVP ([0-9 ]+)\r?$', audio or '')
        if not media or int(media.group(1)) == 0:
            d['valid'] = False
            return
        pts = set(int(x) for x in media.group(2).split())
        voice = pts & STATIC_VOICE
        for pt, codec in re.findall(r'(?im)^a=rtpmap:(\d+) ([\w-]+)/', audio):
            pt = int(pt)
            if codec.lower() in ('telephone-event', 'cn'):
                voice.discard(pt)
            elif pt in pts:
                voice.add(pt)
        if any(pt >= 96 and pt not in voice and not re.search(r'(?im)^a=rtpmap:' + str(pt) + r' (telephone-event|CN)/', audio) for pt in pts):
            d['valid'] = False
        d['nonvoice'] = pts - voice
        d['voice'] = voice if not d['voice'] else d['voice'] & voice
        if src in self.addresses:
            d['port'] = int(media.group(1))

    def packet(self, at, src, sp, dst, dp, payload):
        with self.lock:
            if at <= self.capture_after:
                return
            if payload.startswith((b'INVITE ', b'SIP/2.0 ', b'ACK ', b'BYE ', b'CANCEL ')):
                self.sip(at, src, sp, dst, dp, payload)
                return
            r = bytearray(payload)
            if len(r) < 12 or r[0] >> 6 != 2 or 192 <= r[1] <= 223:
                return
            direction = 0 if dst in self.addresses else 1 if src in self.addresses else None
            if direction is None:
                return
            port = dp if direction == 0 else sp
            ds = [d for d in self.dialogs.values() if d['port'] == port and d['answered'] and d['ack'] and d['valid']]
            if len(ds) != 1:
                return
            d = ds[0]
            if (r[1] & 127) not in d['voice']:
                if direction == 0 and (r[1] & 127) in d['nonvoice']:
                    d['control_rx'] += 1
                return
            key = (direction, bytes(r[2:12]))
            if key in d['seen']:
                return
            if len(d['seen']) > 30000:
                d['valid'] = False
                return
            d['seen'].add(key)
            # Counters only run after independent bridge confirmation.
            if any(d is self.dialogs.get(c) for pair in self.pairs for c in pair):
                d['counts'][direction] += 1

    def confirm(self, extension_pairs, now):
        with self.lock:
            keep = set()
            for left, right in extension_pairs:
                a = [(c,d) for c,d in self.dialogs.items() if d['ext'] == left and d['valid'] and d['answered'] and d['ack']]
                b = [(c,d) for c,d in self.dialogs.items() if d['ext'] == right and d['valid'] and d['answered'] and d['ack']]
                if len(a) != 1 or len(b) != 1 or a[0][0] == b[0][0]:
                    continue
                pair = tuple(sorted([a[0][0], b[0][0]]))
                keep.add(pair)
                if pair not in self.pairs:
                    for cid in pair:
                        self.dialogs[cid]['counts'] = [0,0]
                        self.dialogs[cid]['control_rx'] = 0
                        self.dialogs[cid]['seen'] = set()
                    self.pairs[pair] = now
            for pair in list(self.pairs):
                if pair not in keep:
                    self.emit(pair, now)
                    self.pairs.pop(pair, None)

    def emit(self, pair, now):
        start = self.pairs[pair]
        ds = [self.dialogs.get(c) for c in pair]
        if now-start < 10 or not all(ds):
            return
        for i, d in enumerate(ds):
            if d['ext'] not in self.expected:
                continue
            other = ds[1-i]
            self.completed.append({'extension': d['ext'], 'answered_bridge': True,
                'evidence_kind': 'passive_bridge_transport_v1',
                'peer_extension': other['ext'],
                # These states follow from the independent Up bridge and valid
                # bidirectional SDP. Hardware mute/operator identity are unknown.
                'on_hold': False, 'ringing': False, 'queue_announcement': False,
                'known_mute': None, 'connected_operator': None,
                'capture_dropped': not self.complete,
                'capture_ambiguous': not all(x['valid'] for x in ds),
                'capture_replayed': False, 'dtmf_excluded': True,
                'comfort_noise_excluded': True,
                'capture_complete': self.complete and all(x['valid'] and x['port'] and x['voice'] and not (x['counts'][0] == 0 and x['control_rx'] > 0) for x in ds),
                'window_end': now, 'window_seconds': now-start,
                'voice_packets': dict(zip(['site_rx','site_tx','operator_rx','operator_tx'], d['counts']+other['counts']))})
        for d in ds:
            d['counts'] = [0,0]
            d['control_rx'] = 0
            d['seen'] = set()
        self.pairs[pair] = now

    def close(self, cid, now):
        for pair in list(self.pairs):
            if cid in pair:
                self.emit(pair, now)
                self.pairs.pop(pair, None)
        self.dialogs.pop(cid, None)

    def report_calls(self, now):
        with self.lock:
            for pair in list(self.pairs):
                if now-self.pairs[pair] >= 20:
                    self.emit(pair, now)
            for cid,d in list(self.dialogs.items()):
                if now-d['start'] > 3600:
                    self.close(cid, now)
            self.completed = [r for r in self.completed if now-r['window_end'] <= 150][-2000:]
            return [dict(r, capture_complete=bool(r['capture_complete'] and self.complete)) for r in self.completed]


def bridge_pairs(concise):
    rows = [l.split('!') for l in concise.splitlines()]
    rows = [r for r in rows if len(r) >= 14 and r[4] == 'Up' and re.match(r'^[a-f0-9-]{36}$',r[12])]
    parent = {}
    def root(x):
        parent.setdefault(x,x)
        while parent[x] != x:
            x = parent[x]
        return x
    local = collections.defaultdict(list)
    for r in rows:
        root(r[12])
        if r[0].startswith('Local/'):
            local[r[0].rsplit(';',1)[0]].append(r[12])
    for values in local.values():
        if len(values) == 2:
            parent[root(values[0])] = root(values[1])
    groups = collections.defaultdict(list)
    for r in rows:
        if re.match(r'^PJSIP/[0-9]+-[a-f0-9]+$',r[0]):
            groups[root(r[12])].append(r[0].split('/')[1].split('-')[0])
    return [tuple(v) for v in groups.values() if len(v) == 2 and v[0] != v[1]]

def bridges():
    return bridge_pairs(command(['asterisk','-rx','core show channels concise']))


def route_evidence(status_path, manifest_path, expected, now):
    """Use fresh guard readback only for destinations it explicitly approved."""
    result = dict((ext, None) for ext in expected)
    try:
        with open(status_path) as stream:
            status = json.loads(stream.read(65536))
        with open(manifest_path) as stream:
            manifest = json.loads(stream.read(65536))
        if not -30 <= now - float(status['at']) <= 90:
            return result
        approved = set(row['extension'] for row in manifest['approved'])
        if status['approved_count'] != len(approved):
            return result
        problems = dict((row[0], row[1]) for row in status['alerts'])
        faults = set(['saved_peer_drift', 'conflicting_exact_peer',
                      'runtime_drift_repair_deferred',
                      'cloud_registration_without_approved_return_route'])
        for ext in expected:
            if problems.get(ext) in faults:
                result[ext] = False
            elif ext in approved and ext not in problems and status['cloud_peer_handshake_age'] <= 180:
                result[ext] = True
    except (IOError, OSError, ValueError, KeyError, TypeError):
        return dict((ext, None) for ext in expected)
    return result


def queue_evidence(path, expected, now):
    """Read one bounded, complete five-minute window; unavailable stays unknown."""
    try:
        with open(path, 'rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            offset = max(0, size - MAX_TEXT)
            stream.seek(offset)
            text = stream.read(MAX_TEXT)
        if offset:
            text = text.split(b'\n', 1)[-1]
        return summarize_queue_calls(text.decode('utf8', 'replace'), expected, now,
                                     starts_at_beginning=not offset)
    except (IOError, OSError, ValueError):
        return {'complete': False, 'window_seconds': 300, 'observed_at': now,
                'short_answered_calls_5m': {}}


def snapshot(config, evidence, previous):
    now = time.time()
    endpoints = []
    firewall = {}
    complete = False
    try:
        s = command(['asterisk','-rx','pjsip show contacts'])
        complete = 'Objects found:' in s
        available = {}
        for ext, state in re.findall(r'Contact:\s+([0-9]+)/\S+\s+\S+\s+(Avail|Unavail|Unknown)', s):
            available[ext] = state == 'Avail'
        for ext in config['expected_extensions']:
            endpoints.append({'extension':ext, 'qualified': available.get(ext, False) if complete else None,
                'return_route_valid':None, 'site_firewall_present':None, 'disconnects_5m':None})
        rules = command(['iptables','-S'])
        firewall['rtp_allowance_present'] = '-A fpbx-rtp -p udp -m udp --dport 10000:20000 -j ACCEPT' in rules
        sip = [l for l in rules.splitlines() if 'vpn-us-central-pbx' in l]
        firewall['managed_sip_rule_present'] = any(l.startswith('-A fpbxfirewall ') and '-s 10.254.250.5/32 ' in l and '-d 10.253.250.11/32 ' in l and '--dport 5062 ' in l for l in sip)
        firewall['input_order_valid'] = '-A INPUT -j fpbxfirewall' in rules and not any(l.startswith('-A INPUT ') for l in sip)
    except Exception as e:
        print('probe error: '+type(e).__name__, file=sys.stderr)
    now = time.time()
    stability = queue_evidence(config.get('queue_log', '/var/log/asterisk/queue_log'),
                               config['expected_extensions'], now)
    routes = route_evidence(config.get('route_guard_status', '/var/lib/unique-audio-guard/status.json'),
                            config.get('route_guard_manifest', '/etc/unique-audio-guard.json'),
                            config['expected_extensions'], now)
    for endpoint in endpoints:
        endpoint['return_route_valid'] = routes.get(endpoint['extension'])
        endpoint['short_answered_calls_5m'] = stability['short_answered_calls_5m'].get(endpoint['extension'])
    return {'version':1,'source_id':config['source_id'],'observed_at':now,
        'registrations_complete':complete,'firewall':firewall,'endpoints':endpoints,
        'calls':evidence.report_calls(now), 'call_stability_complete':stability['complete']}


def capture(evidence, proc, errors):
    def exact(n):
        out = b''
        while len(out)<n:
            chunk = proc.stdout.read(n-len(out))
            if not chunk: raise EOFError()
            out += chunk
        return out
    try:
        header = exact(24)
        endian = '<' if header[:4] == b'\xd4\xc3\xb2\xa1' else '>'
        link = struct.unpack(endian+'I',header[20:24])[0]
        while True:
            sec,usec,n,original = struct.unpack(endian+'IIII',exact(16))
            if n > 65535: raise ValueError('capture length')
            packet = ipv4_udp(exact(n),link)
            if packet: evidence.packet(sec+usec/1e6,*packet)
    except Exception as e:
        evidence.complete = False
        errors.append(type(e).__name__)


def upload_worker(config, pending):
    while True:
        p = pending.get()
        try:
            command(['/usr/local/bin/aws','s3','cp',p,config['s3_uri'],'--only-show-errors',
                '--cli-connect-timeout','5','--cli-read-timeout','10'],35)
        except Exception as e:
            print('Evidence upload failed: '+type(e).__name__,file=sys.stderr)
        finally:
            pending.task_done()

class CaptureStats(object):
    """Require fresh statistics and a clean interval, not a zero lifetime total."""
    def __init__(self):
        self.condition = threading.Condition()
        self.generation = 0
        self.drops = None
        self.previous = None
        self.observed_at = 0

    def record(self, drops):
        with self.condition:
            self.drops = drops
            self.observed_at = time.time()
            self.generation += 1
            self.condition.notifyAll()

    def sample(self, proc, timeout=2):
        with self.condition:
            generation = self.generation
            proc.send_signal(signal.SIGUSR1)
            deadline = time.time() + timeout
            while self.generation == generation:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.previous = None
                    return False, time.time(), None
                self.condition.wait(remaining)
            healthy = self.previous is not None and self.drops == self.previous
            delta = None if self.previous is None else self.drops - self.previous
            self.previous = self.drops
            return healthy, self.observed_at, delta


def capture_diagnostics(proc, config, stats):
    lines = collections.deque(maxlen=12)
    for raw in iter(proc.stderr.readline, b''):
        line = raw.decode('utf8','replace')
        lines.append(line)
        drops = re.search(r'(\d+) packets dropped by kernel',line)
        if drops:
            stats.record(int(drops.group(1)))
        p=config['capture_status']
        with open(p+'.tmp','w') as f:
            f.write(''.join(lines))
        os.rename(p+'.tmp',p)

def run(config):
    addresses = config['pbx_addresses']
    evidence = Evidence(addresses,config['expected_extensions'])
    proc = subprocess.Popen(['tcpdump','-U','-B','8192','-ni','any','-s','2048','-w','-',
        'udp and ('+' or '.join('host '+a for a in addresses)+') and (port 5060 or port 5062 or port 5070 or portrange 10000-20000)'], stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    errors=[];stats=CaptureStats();pending=queue.Queue(maxsize=1)
    threads=[threading.Thread(target=capture,args=(evidence,proc,errors)),
        threading.Thread(target=capture_diagnostics,args=(proc,config,stats))]
    if config.get('s3_uri'):
        threads.append(threading.Thread(target=upload_worker,args=(config,pending)))
    for thread in threads:
        thread.daemon=True;thread.start()
    last=time.time()
    try:
        while proc.poll() is None and not errors:
            try: evidence.confirm(bridges(),time.time())
            except Exception:
                with evidence.lock:
                    evidence.pairs.clear()
            now=time.time()
            if now-last>=20:
                healthy, observed_at, delta = stats.sample(proc)
                evidence.capture_health(healthy and not errors, observed_at)
                value=snapshot(config,evidence,None)
                value['capture_health'] = {
                    'complete': bool(healthy and not errors),
                    'observed_at': observed_at,
                    'kernel_drops_total': stats.drops,
                    'kernel_drops_interval': delta,
                    'reason': 'clean_interval' if healthy and not errors else
                              'startup_stale_or_dropped_capture',
                }
                p=config['output']
                with open(p+'.tmp','w') as f:json.dump(value,f)
                os.chmod(p+'.tmp',0o600);os.rename(p+'.tmp',p)
                if config.get('s3_uri'):
                    try:pending.put_nowait(p)
                    except queue.Full:pass
                last=now
            time.sleep(1)
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait()
    raise RuntimeError('packet collector stopped: '+str(errors))

if __name__ == '__main__':
    os.environ['PATH']='/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    os.environ['AWS_MAX_ATTEMPTS']='2'
    run(json.load(open(sys.argv[1])))
