"""Immutable local generations and cold copies, not off-machine attestation."""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import stat

import foundation_preservation as preservation
import workbench_evidence as ev
from workbench_backup import durable_directory, fsync_directory, write_new


def _destination(value, sources):
    root = Path(value).absolute()
    # governance-mutation: FOUNDATION_LOCAL_PARENT_ALIAS
    if '..' in root.parts or root.exists() or root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError('LOCAL_STORE_NEW_ROOT_REQUIRED')
    for source in sources:
        source = Path(source).absolute()
        if source == root or source in root.parents or root in source.parents:
            raise ValueError('LOCAL_STORE_ROOTS_OVERLAP')
    return root


def _inventory(root):
    return preservation._inventory(preservation._root(root), max_bytes=preservation.MAX_TOTAL_BYTES,
                                    max_entries=preservation.MAX_ENTRIES)


def _reserve(root):
    durable_directory(root.parent)
    # governance-mutation: FOUNDATION_LOCAL_EXCLUSIVE_ROOT
    root.mkdir(mode=0o700)  # Exclusive: never adopt a concurrent directory.
    fsync_directory(root); fsync_directory(root.parent)


def _copy(source, destination, inventory):
    from foundation_sources import _open_readonly
    source = preservation._root(source)
    _reserve(destination)
    for name in inventory['directories']:
        durable_directory(destination / name)
    total = 0
    for name, expected in inventory['files'].items():
        source_fd = _open_readonly(Path(source) / name)
        with os.fdopen(source_fd, 'rb') as reader:
            before = os.fstat(reader.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > preservation.MAX_FILE_BYTES:
                raise ValueError('LOCAL_STORE_SOURCE_FILE_INVALID')
            target = destination / name
            durable_directory(target.parent)
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            checksum, size = hashlib.sha256(), 0
            with os.fdopen(fd, 'wb') as writer:
                while True:
                    block = reader.read(min(preservation.CHUNK_BYTES, before.st_size - size + 1))
                    if not block: break
                    size += len(block); total += len(block)
                    if size > before.st_size or total > inventory['total_bytes']:
                        raise ValueError('LOCAL_STORE_COPY_SIZE_LIMIT')
                    writer.write(block); checksum.update(block)
                # governance-mutation: FOUNDATION_LOCAL_PAYLOAD_DURABLE
                writer.flush(); os.fsync(writer.fileno())
            if (size != before.st_size or checksum.hexdigest() != expected
                    or preservation._stamp(before) != preservation._stamp(os.fstat(reader.fileno()))):
                raise ValueError('LOCAL_STORE_SOURCE_CHANGED')
    for path in sorted((p for p in destination.rglob('*') if p.is_dir()), reverse=True):
        fsync_directory(path)
    fsync_directory(destination)
    if _inventory(destination) != inventory:
        raise ValueError('LOCAL_STORE_COPY_INVENTORY_CONFLICT')


def _trust(root):
    from experiments.research_funnel.research_trust import _read_ledger_unlocked
    inventory = _inventory(root)
    if inventory['directories'] or set(inventory['files']) != {'trust_lines.jsonl', 'trust_lines.jsonl.anchor.json'}:
        raise ValueError('LOCAL_STORE_TRUST_FILE_SET_INVALID')
    lines = _read_ledger_unlocked(root / 'trust_lines.jsonl')
    if inventory != _inventory(root):
        raise ValueError('LOCAL_STORE_TRUST_CHANGED')
    return {'files': inventory['files'], 'records': len(lines),
            'head_hash': lines[-1]['hash'] if lines else None,
            'scope': 'HASH_CHAIN_ONLY_NOT_RESEARCH_APPROVAL'}


def create_generation(packages, destination, *, created_at, trust_root=None):
    manifest = preservation.build_preservation_manifest(packages, created_at=created_at)
    sources = {row['package_id']: preservation._root(row['local_root']) for row in packages}
    root = _destination(destination, [*sources.values(), *([trust_root] if trust_root else [])])
    trust = _trust(Path(trust_root)) if trust_root else None
    _reserve(root)
    durable_directory(root / 'packages')
    for identity, source in sources.items():
        row = next(row for row in manifest['packages'] if row['package_id'] == identity)
        _copy(source, root / 'packages' / identity,
              {key: row[key] for key in ('files', 'directories', 'total_bytes')})
    if trust_root:
        _copy(trust_root, root / 'trust', _inventory(Path(trust_root)))
        if _trust(root / 'trust') != trust or _trust(Path(trust_root)) != trust:
            raise ValueError('LOCAL_STORE_TRUST_CHANGED')
    preservation.verify_preservation_copy(manifest,
        {key: root / 'packages' / key for key in sources},
        expected_preservation_hash=manifest['preservation_hash'])
    preservation.verify_preservation_copy(manifest, sources,
        expected_preservation_hash=manifest['preservation_hash'])
    write_new(root / 'preservation.json', ev.canonical(manifest).encode())
    receipt = {'schema': 'ar.local-preservation.v1', 'preservation_hash': manifest['preservation_hash'],
               'trust': trust, 'inventory': _inventory(root), 'off_machine': 'NOT_ATTESTED',
               'human_review': 'PENDING', 'production_authority': False,
               'sample_purpose': 'WORKFLOW_DEBUG'}
    receipt['generation_hash'] = ev.sealed(receipt)
    # The complete marker is last; partial directories remain evidence, not accepted generations.
    write_new(root / 'generation.json', ev.canonical(receipt).encode())
    verify_generation(root, expected_generation_hash=receipt['generation_hash'])
    return receipt


def verify_generation(root, *, expected_generation_hash):
    root = preservation._root(root)
    receipt = ev.parse(ev.read_local(root, 'generation.json'))
    if (set(receipt) != {'schema', 'preservation_hash', 'trust', 'inventory', 'off_machine',
                         'human_review', 'production_authority', 'sample_purpose', 'generation_hash'}
            or receipt['schema'] != 'ar.local-preservation.v1'
            or receipt['off_machine'] != 'NOT_ATTESTED' or receipt['human_review'] != 'PENDING'
            or receipt['production_authority'] is not False or receipt['sample_purpose'] != 'WORKFLOW_DEBUG'
            # governance-mutation: FOUNDATION_LOCAL_EXTERNAL_PIN
            or receipt['generation_hash'] != expected_generation_hash
            or ev.sealed({k: v for k, v in receipt.items() if k != 'generation_hash'}) != expected_generation_hash):
        raise ValueError('LOCAL_STORE_GENERATION_BINDING_INVALID')
    inventory = _inventory(root)
    del inventory['files']['generation.json']
    inventory['total_bytes'] -= (root / 'generation.json').stat().st_size
    # governance-mutation: FOUNDATION_LOCAL_INVENTORY
    if inventory != receipt['inventory']:
        raise ValueError('LOCAL_STORE_INVENTORY_MISMATCH')
    manifest = ev.parse(ev.read_local(root, 'preservation.json'))
    preservation.verify_preservation_copy(manifest,
        {row['package_id']: root / 'packages' / row['package_id'] for row in manifest['packages']},
        expected_preservation_hash=receipt['preservation_hash'])
    if receipt['trust'] is not None and _trust(root / 'trust') != receipt['trust']:
        raise ValueError('LOCAL_STORE_TRUST_MISMATCH')
    return receipt


def restore_generation(source, destination, *, expected_generation_hash):
    source = preservation._root(source)
    expected = verify_generation(source, expected_generation_hash=expected_generation_hash)
    target = _destination(destination, [source])
    _copy(source, target, _inventory(source))
    restored = verify_generation(target, expected_generation_hash=expected_generation_hash)
    if verify_generation(source, expected_generation_hash=expected_generation_hash) != restored or restored != expected:
        raise ValueError('LOCAL_STORE_RESTORE_CHANGED')
    fsync_directory(target)
    return restored
