"""Fresh inventory bytes and guarded descriptor traversal, never a proof cache."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts/llm'),str(ROOT)]
import workbench_shared_cards as cards


class CardInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/'source'
        self.root.mkdir()

    def test_bulk_inventory_opens_ancestors_once_not_for_each_payload(self):
        expected={}
        for i in range(80):
            raw=('frozen-'+str(i)).encode();name=f'file-{i}.json'
            (self.root/name).write_bytes(raw)
            expected['pack/'+name]=hashlib.sha256(raw).hexdigest()
        with patch.object(os,'open',wraps=os.open) as opened:
            actual=cards._files({'pack':self.root})
        self.assertEqual(actual,expected)
        self.assertLess(opened.call_count,160,'every byte stays verified without reopening every ancestor per file')

    def test_each_inventory_rereads_bytes_not_size_or_mtime(self):
        path=self.root/'entry.json';path.write_bytes(b'one')
        first=cards._files({'pack':self.root});before=path.stat()
        path.write_bytes(b'two');os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        second=cards._files({'pack':self.root})
        self.assertNotEqual(first,second)
        self.assertEqual(second['pack/entry.json'],hashlib.sha256(b'two').hexdigest())

    def test_link_special_mode_and_empty_directory_still_refused(self):
        target=self.root/'ok.json';target.write_bytes(b'{}')
        for kind in ('symlink','hardlink','executable','unreadable','fifo','empty'):
            with self.subTest(kind=kind):
                member=self.root/'bad'
                try:
                    if kind=='symlink':member.symlink_to(target)
                    elif kind=='hardlink':os.link(target,member)
                    elif kind=='executable':target.chmod(0o700)
                    elif kind=='unreadable':target.chmod(0o200)
                    elif kind=='fifo':os.mkfifo(member)
                    else:member.mkdir()
                    with self.assertRaises((ValueError,OSError)):
                        cards._files({'pack':self.root})
                finally:
                    target.chmod(0o600)
                    if member.is_dir() and not member.is_symlink():member.rmdir()
                    elif member.exists() or member.is_symlink():member.unlink()

    def test_ancestor_replacement_after_read_is_not_adopted(self):
        parent=self.root/'parent';parent.mkdir();root=parent/'nested';root.mkdir()
        (root/'value').write_bytes(b'frozen')
        original=os.read;changed=False
        def replace(fd,size):
            nonlocal changed
            raw=original(fd,size)
            if raw and not changed:
                changed=True;parent.rename(self.root/'old-parent')
                root.mkdir(parents=True);(root/'value').write_bytes(b'frozen')
            return raw
        with patch.object(os,'read',side_effect=replace):
            with self.assertRaisesRegex(ValueError,'CHANGED_DURING_READ'):cards._files({'pack':root})
        self.assertTrue(changed)

    def test_in_place_change_while_streaming_is_refused(self):
        path=self.root/'value';path.write_bytes(b'original')
        original=os.read;changed=False
        def change(fd,size):
            nonlocal changed
            raw=original(fd,size)
            if raw and not changed:changed=True;path.write_bytes(b'modified')
            return raw
        with patch.object(os,'read',side_effect=change):
            with self.assertRaisesRegex(ValueError,'CHANGED_DURING_READ'):cards._files({'pack':self.root})

    def test_payload_limit_and_file_count_are_not_expanded(self):
        import workbench_evidence as ev
        huge=self.root/'huge'
        with huge.open('wb') as file:file.truncate(ev.MAX_FILE+1)
        with self.assertRaises(ValueError):cards._files({'pack':self.root})
        huge.unlink()
        for i in range(257):(self.root/str(i)).write_bytes(b'')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_LIMIT'):cards._files({'pack':self.root})


if __name__=='__main__':unittest.main()
