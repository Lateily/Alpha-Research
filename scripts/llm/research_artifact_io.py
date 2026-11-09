"""Descriptor-pinned, manifest-last publication for the two offline research cards."""
from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import secrets
import stat
import sys

import foundation_materials as materials
import workbench_evidence as ev
from experiments.research_workflows import technical_contract as directory_io

PENDING = '.artifact-manifest.pending'
PROVISION_BASE = Path('/private/tmp' if sys.platform == 'darwin' else '/tmp')


def _no_acl(fd):
    if sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        get_acl = libc.acl_get_fd_np
        get_acl.argtypes = (ctypes.c_int, ctypes.c_int)
        get_acl.restype = ctypes.c_void_p
        get_entry = libc.acl_get_entry
        get_entry.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
        release = libc.acl_free
        release.argtypes = (ctypes.c_void_p,)
        ctypes.set_errno(0)
        acl = get_acl(fd, 0x100)  # SDK ACL_TYPE_EXTENDED
        if not acl:
            if ctypes.get_errno() == errno.ENOENT and stat.S_ISDIR(os.fstat(fd).st_mode):
                return
            raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNTRUSTED')
        try:
            entry = ctypes.c_void_p()
            valid = libc.acl_valid
            valid.argtypes = (ctypes.c_void_p,)
            if valid(acl):
                raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNTRUSTED')
            ctypes.set_errno(0)
            if get_entry(acl, 0, ctypes.byref(entry)) != -1 or ctypes.get_errno() != errno.EINVAL:
                raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNTRUSTED')
        finally:
            release(acl)
    elif sys.platform.startswith('linux'):
        if any(name in {'system.posix_acl_access', 'system.posix_acl_default'} for name in os.listxattr(fd)):
            raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNTRUSTED')
    else:
        raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNSUPPORTED')


def _trusted_directory(fd):
    info = os.fstat(fd)
    sticky_system = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}
            or (info.st_mode & 0o022 and not sticky_system)):
        raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNTRUSTED')
    _no_acl(fd)


@contextmanager
def _provision_parent():
    # Trust OS/root and this user's code, not arbitrary same-UID hostile processes.
    # A root-owned sticky temp ancestor prevents other users replacing our child.
    path = PROVISION_BASE.resolve(strict=True)
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _trusted_directory(fd)
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            _trusted_directory(fd)
        directory_io._output_current(path, fd)
        yield path, fd
        directory_io._output_current(path, fd)
    finally:
        os.close(fd)


def _rename_exclusive(source_parent, source, target_parent, target):
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        operation, flags = getattr(libc, 'renameatx_np', None), 4  # SDK RENAME_EXCL
    elif sys.platform.startswith('linux'):
        operation, flags = getattr(libc, 'renameat2', None), 1  # RENAME_NOREPLACE
    else:
        operation, flags = None, None
    if operation is None:
        raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNSUPPORTED')
    operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    operation.restype = ctypes.c_int
    # governance-mutation: RESEARCH_ARTIFACT_EXCLUSIVE_ROOT
    if operation(source_parent, os.fsencode(source), target_parent, os.fsencode(target), flags):
        code = ctypes.get_errno()
        if code in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ev.EvidenceError('OUTPUT_EXISTS')
        raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_REFUSED')


@contextmanager
def _new_output(output):
    fd = None
    try:
        with directory_io._directory(output.parent) as target_parent, _provision_parent() as (path, parent):
            if os.fstat(parent).st_dev != os.fstat(target_parent).st_dev:
                raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_CROSS_DEVICE')
            name = '.ar-research-' + secrets.token_hex(24)
            os.mkdir(name, mode=0o700, dir_fd=parent)
            created = os.stat(name, dir_fd=parent, follow_symlinks=False)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            held = os.fstat(fd)
            if ((held.st_dev, held.st_ino) != (created.st_dev, created.st_ino)
                    or held.st_uid != os.geteuid() or stat.S_IMODE(held.st_mode) != 0o700):
                raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_UNTRUSTED')
            _no_acl(fd)
            _inventory(fd, set())
            directory_io._output_current(path, parent)
            directory_io._output_current(output.parent, target_parent)
            _rename_exclusive(parent, name, target_parent, output.name)
            os.fsync(parent)
            os.fsync(target_parent)
            # Never acquire initial ownership from the now-public pathname.
            directory_io._output_current(output, fd)
            yield fd
    except OSError:
        raise ev.EvidenceError('RESEARCH_ARTIFACT_PROVISION_REFUSED') from None
    finally:
        if fd is not None:
            os.close(fd)


def _inventory(fd, names):
    if materials._names(fd, len(names)) != set(names):
        raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_INVENTORY')


def _read_file(root_fd, relative):
    parts = directory_io._relative(relative)
    if len(parts) != 1:
        raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_LAYOUT')
    fd = None
    try:
        fd = os.open(relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED')
        # governance-mutation: RESEARCH_ARTIFACT_READ_PREFLIGHT_CAP
        if before.st_size > ev.MAX_FILE:
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_SIZE')
        chunks, size = [], 0
        while True:
            # governance-mutation: RESEARCH_ARTIFACT_READ_REQUEST_BOUND
            chunk = os.read(fd, min(65536, ev.MAX_FILE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > ev.MAX_FILE:
                raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_SIZE')
            chunks.append(chunk)
        after = os.fstat(fd)
        named = os.stat(relative, dir_fd=root_fd, follow_symlinks=False)
        identity = directory_io._fingerprint
        if identity(before) != identity(after) or identity(after) != identity(named):
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED')
        return b''.join(chunks), identity(after)
    except OSError:
        raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED') from None
    finally:
        if fd is not None:
            os.close(fd)


def _verify_files(fd, hashes):
    for name, pin in hashes.items():
        if ev.sha(_read_file(fd, name)[0]) != pin:
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED')


@contextmanager
def read(root, names):
    """Hold directory identity and all file fingerprints across derivation."""
    output = materials._root(root)
    with directory_io._directory(output) as fd:
        _inventory(fd, names)
        saved = {name: _read_file(fd, name) for name in names}
        yield {name: pair[0] for name, pair in saved.items()}
        directory_io._output_current(output, fd)
        _inventory(fd, names)
        # governance-mutation: RESEARCH_ARTIFACT_READ_SNAPSHOT
        if any(_read_file(fd, name) != pair for name, pair in saved.items()):
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED')


def publish(output, files, marker, encoded, verify):
    """Publish only our newly created root; retract only our own commit on failure."""
    names = {*files, marker}
    if marker in files or PENDING in names or len(names) > 8:
        raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_LAYOUT')
    for name in names:
        if len(directory_io._relative(name)) != 1:
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_LAYOUT')
    if any(len(raw) > ev.MAX_FILE for raw in (*files.values(), encoded)):
        raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_SIZE')
    hashes = {name: ev.sha(raw) for name, raw in files.items()}
    with _new_output(output) as fd:
        for name, raw in files.items():
            # governance-mutation: RESEARCH_ARTIFACT_HELD_WRITES
            directory_io._write_new(output, fd, name, raw)
        directory_io._write_new(output, fd, PENDING, encoded)
        _verify_files(fd, hashes)
        staged, identity = _read_file(fd, PENDING)
        if staged != encoded:
            raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED')
        directory_io._output_current(output, fd)
        _inventory(fd, {*files, PENDING})
        os.fsync(fd)
        published = False
        try:
            os.link(PENDING, marker, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            published = True
            for name in (PENDING, marker):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != identity[:2] or info.st_nlink != 2:
                    raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_CHANGED')
            os.unlink(PENDING, dir_fd=fd)
            hashes[marker] = ev.sha(encoded)
            _verify_files(fd, hashes)
            directory_io._output_current(output, fd)
            _inventory(fd, names)
            os.fsync(fd)
            result = verify()
            _verify_files(fd, hashes)
            directory_io._output_current(output, fd)
            _inventory(fd, names)
            return result
        except BaseException:
            # The other files remain as failed evidence; never erase earlier outputs.
            # governance-mutation: RESEARCH_ARTIFACT_COMMIT_ROLLBACK
            if published:
                try:
                    info = os.stat(marker, dir_fd=fd, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == identity[:2]:
                        os.unlink(marker, dir_fd=fd)
                        os.fsync(fd)
                except OSError:
                    pass
            raise
