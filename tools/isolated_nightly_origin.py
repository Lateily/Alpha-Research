"""Read-only origin namespace for isolated recovery, never a live-path override.

An externally pinned context binds five copied files. The unchanged production
verifier sees their original logical names and exact bytes in memory. No old
record is rewritten. This module grants neither production nor trading authority.
Run recovery in a dedicated single-threaded process: module-local views are
installed only for the synchronous verification call and always restored.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import sys
from types import SimpleNamespace

ET_REL = 'experiments/execution_tracker'
STATE = ET_REL + '/publication_state.json'
FILES = frozenset({
    STATE, ET_REL + '/publication_rebaseline_events.jsonl',
    ET_REL + '/publication_rebaseline_events.jsonl.anchor.json',
    ET_REL + '/current_run.json', 'public/data/v2/current_run.json',
})
CONTEXT_KEYS = frozenset({'schema', 'sample_purpose', 'production_authority',
                          'origin_root', 'runtime_root', 'files'})
MAX_BYTES = 16 * 1024 * 1024


def _read_regular(root, relative):
    """Traverse copied directories by fd without following a replaced symlink."""
    parts = relative.split('/')
    if not parts or any(p in ('', '.', '..') for p in parts):
        raise RuntimeError('invalid relative artifact path')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(str(root), flags | os.O_DIRECTORY)
    try:
        for name in parts[:-1]:
            child = os.open(name, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(parts[-1], flags, dir_fd=fd)
        with os.fdopen(child, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise RuntimeError('artifact must be a regular file')
            raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError('artifact exceeds size bound')
            return raw
    finally:
        os.close(fd)


class OriginView:
    def __init__(self, origin, runtime, blobs):
        self.origin, self.runtime, self.blobs = origin, runtime, blobs
        self.path = SimpleNamespace(
            join=posixpath.join, dirname=posixpath.dirname, normcase=posixpath.normcase,
            abspath=self.logical, realpath=self.logical,
            isabs=posixpath.isabs, exists=self.exists,
            isfile=self.exists, isdir=self.isdir,
        )

    def logical(self, path):
        text = os.fspath(path)
        if (not posixpath.isabs(text) or '..' in text.split('/')
                or posixpath.commonpath([self.origin, text]) != self.origin):
            raise RuntimeError('unregistered origin namespace path')
        return posixpath.normpath(text)

    def exists(self, path):
        name = self.logical(path)
        if name not in self.blobs:
            raise RuntimeError('unregistered origin file probe')
        return True

    def isdir(self, path):
        self.exists(path)
        return False

    def open(self, path, mode='r', encoding=None, **kwargs):
        if mode not in ('r', 'rb') or kwargs:
            raise RuntimeError('origin namespace is read-only')
        name = self.logical(path)
        if name not in self.blobs:
            raise RuntimeError('unregistered origin file read')
        raw = self.blobs[name]
        return io.BytesIO(raw) if mode == 'rb' else io.StringIO(raw.decode(encoding or 'utf-8'))


def load_context(path, expected_sha256):
    path = Path(path).absolute()
    raw = _read_regular(path.parent, path.name)
    # External pin is a content binding, not cryptographic human authorization.
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError('context hash mismatch')
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) != CONTEXT_KEYS:
        raise RuntimeError('invalid context field set')
    if (obj['schema'] != 'ar.isolated-origin.v1'
            or obj['sample_purpose'] != 'WORKFLOW_DEBUG'
            or obj['production_authority'] is not False):
        raise RuntimeError('invalid context authority or purpose')
    origin, runtime = obj['origin_root'], obj['runtime_root']
    for root in (origin, runtime):
        if not isinstance(root, str) or not posixpath.isabs(root) or posixpath.normpath(root) != root or root == '/':
            raise RuntimeError('context requires canonical absolute roots')
    if posixpath.commonpath([origin, runtime]) in (origin, runtime):
        raise RuntimeError('origin and runtime must be disjoint')
    if str(Path(runtime).resolve(strict=True)) != runtime:
        raise RuntimeError('runtime root must not contain symlinks')
    if not isinstance(obj['files'], dict) or set(obj['files']) != FILES:
        raise RuntimeError('closed origin artifact set required')
    blobs = {}
    for rel, expected in obj['files'].items():
        if not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None:
            raise RuntimeError('invalid artifact digest')
        content = _read_regular(runtime, rel)
        if hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError('artifact hash mismatch: ' + rel)
        blobs[posixpath.join(origin, rel)] = content
    return OriginView(origin, runtime, blobs)


def _modules():
    et = Path(__file__).resolve().parents[1] / ET_REL
    if str(et) not in sys.path:
        sys.path.insert(0, str(et))
    import nightly_publish
    import event_ledger
    return nightly_publish, event_ledger


@contextlib.contextmanager
def _read_view(view, modules):
    absent = object()
    saved = []
    try:
        for module in modules:
            saved.append((module, module.os, getattr(module, 'open', absent)))
            module.os = SimpleNamespace(path=view.path)
            module.open = view.open
        yield
    finally:
        for module, old_os, old_open in reversed(saved):
            module.os = old_os
            if old_open is absent:
                del module.open
            else:
                module.open = old_open


def verify_context(path, expected_sha256, publication=None):
    view = load_context(path, expected_sha256)
    default, ledger = _modules()
    publication = publication or default
    state = json.loads(view.blobs[posixpath.join(view.origin, STATE)])
    if state.get('status') != 'SUPERSEDED_BY_OPERATOR':
        raise RuntimeError('origin compatibility supports only a sealed SUPERSEDED state')
    recover = publication.recover_interrupted_publish
    with _read_view(view, (publication, ledger)):
        return recover(posixpath.join(view.origin, STATE),
                       posixpath.join(view.origin, ET_REL), view.origin)


@contextlib.contextmanager
def relocated_recovery(path, expected_sha256, publication=None):
    """Adapt only the frozen old state; new publication recovery stays canonical."""
    default, _ = _modules()
    publication = publication or default
    view = load_context(path, expected_sha256)
    original = publication.recover_interrupted_publish
    expected_state = posixpath.join(view.runtime, STATE)
    expected_et = posixpath.join(view.runtime, ET_REL)
    frozen_event = json.loads(view.blobs[posixpath.join(view.origin, STATE)])['superseded_event_hash']
    # Exercise every guard before installing any interception.
    verify_context(path, expected_sha256, publication)

    def recover(state_path, live_et, live_repo):
        if (os.path.abspath(state_path) != expected_state
                or os.path.abspath(live_et) != expected_et
                or os.path.abspath(live_repo) != view.runtime):
            return original(state_path, live_et, live_repo)
        current = _read_regular(view.runtime, STATE)
        current_state = json.loads(current)
        if (current_state.get('status') != 'SUPERSEDED_BY_OPERATOR'
                or current_state.get('superseded_event_hash') != frozen_event):
            return original(state_path, live_et, live_repo)
        fresh = load_context(path, expected_sha256)
        _, ledger = _modules()
        with _read_view(fresh, (publication, ledger)):
            return original(posixpath.join(fresh.origin, STATE),
                            posixpath.join(fresh.origin, ET_REL), fresh.origin)

    publication.recover_interrupted_publish = recover
    try:
        yield
    finally:
        publication.recover_interrupted_publish = original
