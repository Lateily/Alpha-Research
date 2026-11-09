"""Descriptor-pinned, manifest-last publication for the two offline research cards."""
from contextlib import contextmanager
import os
import stat

import foundation_materials as materials
import workbench_evidence as ev
from experiments.research_workflows import technical_contract as directory_io

PENDING = '.artifact-manifest.pending'


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
    with directory_io._new_output(output) as fd:
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
