"""Scoped directory reads retain the safe local evidence boundary without byte caches."""
import errno
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts/llm'), str(ROOT)]
import foundation_results as results
import workbench_evidence as ev


class ScopedEvidenceReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'checked-root'
        self.root.mkdir()
        (self.root / 'piece.json').write_bytes(b'{"a":1}')

    def reader(self, root=None):
        factory = getattr(ev, 'read_root', None)
        self.assertTrue(callable(factory), 'scoped checked-root reader is not implemented')
        return factory(root or self.root)

    def test_tree_reopens_checked_root_a_bounded_number_of_times(self):
        expected = {'piece.json': b'{"a":1}'}
        for index in range(12):
            name = 'item-%02d.json' % index
            expected[name] = b'{"b":2}'
            (self.root / name).write_bytes(expected[name])
        opened = []
        original = os.open
        def observe(name, *args, **kwargs):
            if name == self.root.name:
                opened.append(name)
            return original(name, *args, **kwargs)
        with patch.object(ev.os, 'open', side_effect=observe):
            actual = results._tree(self.root)
        self.assertEqual(actual, expected)
        self.assertLessEqual(len(opened), 3, 'one checked tree must not reopen all absolute ancestors per file')

    def test_same_scope_and_new_scope_read_current_bytes_not_cached_values(self):
        with self.reader() as read:
            self.assertEqual(read('piece.json'), b'{"a":1}')
            (self.root / 'piece.json').write_bytes(b'{"a":2}')
            self.assertEqual(read('piece.json'), b'{"a":2}')
        (self.root / 'piece.json').write_bytes(b'{"a":3}')
        with self.reader() as read:
            self.assertEqual(read('piece.json'), b'{"a":3}')

    def test_closed_reader_cannot_use_a_recycled_descriptor(self):
        with self.reader() as read:
            self.assertEqual(read('piece.json'), b'{"a":1}')
        with self.assertRaises(ev.EvidenceError):
            read('piece.json')

    def test_replacing_root_is_refused_before_returning_the_tree(self):
        with self.assertRaises((OSError, ev.EvidenceError)):
            with self.reader() as read:
                self.assertEqual(read('piece.json'), b'{"a":1}')
                self.root.rename(self.base / 'retired')
                self.root.mkdir()
                (self.root / 'piece.json').write_bytes(b'{"a":2}')

    def test_parent_symlink_substitution_is_refused(self):
        parent = self.base / 'parent'
        parent.mkdir()
        nested = parent / 'nested'
        nested.mkdir()
        (nested / 'file.json').write_bytes(b'{}')
        with self.assertRaises((OSError, ev.EvidenceError)):
            with self.reader(nested) as read:
                self.assertEqual(read('file.json'), b'{}')
                parent.rename(self.base / 'moved-parent')
                parent.symlink_to(self.base / 'moved-parent', target_is_directory=True)

    def test_scoped_leaf_and_child_links_never_open_outside_bytes(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'outside.json').write_bytes(b'outside')
        (self.root / 'leaf.json').symlink_to(outside / 'outside.json')
        (self.root / 'child').symlink_to(outside, target_is_directory=True)
        with self.reader() as read:
            for relative in ('leaf.json', 'child/outside.json', '../outside/outside.json', '/outside.json'):
                with self.subTest(relative=relative), self.assertRaises((OSError, ev.EvidenceError)):
                    read(relative)

    def test_scoped_fifo_and_socket_are_refused_without_opening_devices(self):
        os.mkfifo(self.root / 'fifo')
        server = socket.socket(socket.AF_UNIX)
        self.addCleanup(server.close)
        server.bind(str(self.root / 'socket'))
        with self.reader() as read:
            for relative in ('fifo', 'socket'):
                with self.subTest(relative=relative), self.assertRaises((OSError, ev.EvidenceError)):
                    read(relative)

    def test_scoped_size_and_read_permission_guards_remain_active(self):
        unreadable = self.root / 'unreadable.json'
        unreadable.write_bytes(b'{}')
        unreadable.chmod(0o200)
        with self.reader() as read:
            with self.assertRaises(ev.EvidenceError):
                read('unreadable.json')
            with patch.object(ev, 'MAX_FILE', 4), self.assertRaises(ev.EvidenceError):
                read('piece.json')

    def test_mutation_during_file_read_is_refused(self):
        original = os.fdopen
        target = self.root / 'piece.json'
        class ChangingStream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def fileno(self):
                return self.stream.fileno()
            def read(self, *args):
                raw = self.stream.read(*args)
                target.write_bytes(b'{"a":987654321}')
                return raw
        with self.reader() as read:
            with patch.object(ev.os, 'fdopen', side_effect=lambda *a, **k: ChangingStream(original(*a, **k))):
                with self.assertRaises(ev.EvidenceError):
                    read('piece.json')

    def test_every_owned_descriptor_closes_on_success_and_failure(self):
        original_open, original_dup = os.open, os.dup
        descriptors = set()
        def opened(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            descriptors.add(fd)
            return fd
        def duplicated(*args, **kwargs):
            fd = original_dup(*args, **kwargs)
            descriptors.add(fd)
            return fd
        with patch.object(ev.os, 'open', side_effect=opened), patch.object(ev.os, 'dup', side_effect=duplicated):
            with self.reader() as read:
                self.assertEqual(read('piece.json'), b'{"a":1}')
            with self.assertRaises(FileNotFoundError):
                with self.reader() as read:
                    read('absent.json')
        for fd in descriptors:
            with self.subTest(fd=fd), self.assertRaises(OSError) as failure:
                os.fstat(fd)
            self.assertEqual(failure.exception.errno, errno.EBADF)

    def test_tree_still_rejects_hard_links_executable_files_and_empty_directories(self):
        for damage in ('hardlink', 'executable', 'empty-directory'):
            target = self.root / damage
            if damage == 'hardlink':
                os.link(self.root / 'piece.json', target)
            elif damage == 'executable':
                target.write_bytes(b'{}')
                target.chmod(0o700)
            else:
                target.mkdir()
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                results._tree(self.root)
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink()


if __name__ == '__main__':
    unittest.main()
