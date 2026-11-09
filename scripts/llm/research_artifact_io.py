"""Descriptor-pinned, manifest-last publication for the two offline research cards."""
from contextlib import contextmanager
import os

import foundation_materials as materials
import workbench_evidence as ev
from experiments.research_workflows import technical_contract as directory_io

PENDING = '.artifact-manifest.pending'


def _inventory(fd, names):
    if materials._names(fd, len(names)) != set(names):
        raise ev.EvidenceError('RESEARCH_ARTIFACT_OUTPUT_INVENTORY')


@contextmanager
def read(root, names):
    """Hold directory identity and all file fingerprints across derivation."""
    output = materials._root(root)
    with directory_io._directory(output) as fd:
        _inventory(fd, names)
        saved = {name: directory_io._read_output(fd, name) for name in names}
        yield {name: pair[0] for name, pair in saved.items()}
        directory_io._output_current(output, fd)
        _inventory(fd, names)
        # governance-mutation: RESEARCH_ARTIFACT_READ_SNAPSHOT
        if any(directory_io._read_output(fd, name) != pair for name, pair in saved.items()):
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
        directory_io._verify_outputs(fd, hashes)
        staged, identity = directory_io._read_output(fd, PENDING)
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
            directory_io._verify_outputs(fd, hashes)
            directory_io._output_current(output, fd)
            _inventory(fd, names)
            os.fsync(fd)
            result = verify()
            directory_io._verify_outputs(fd, hashes)
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
