"""Fresh card inventory hashes with descriptor-relative, no-follow traversal."""
import hashlib
import os
import stat

import foundation_materials as materials
import workbench_evidence as ev


def _stamp(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,
            info.st_mtime_ns,info.st_ctime_ns,info.st_nlink)


def inventory(root):
    root=materials._root(root);files={};total=0;nodes=0
    def walk(fd,prefix=''):
        nonlocal total,nodes
        before=os.fstat(fd);names=[]
        with os.scandir(fd) as entries:
            for entry in entries:
                nodes+=1
                if nodes>4096:raise ValueError('ARTIFACT_LIMIT')
                names.append(entry.name)
        for name in names:
            relative=prefix+name;info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    if _stamp(info)!=_stamp(os.fstat(child)):raise ValueError('SOURCE_CHANGED_DURING_READ')
                    if not walk(child,relative+'/'):raise ValueError('ARTIFACT_DIRECTORY_INVENTORY_INVALID')
                finally:os.close(child)
            elif stat.S_ISREG(info.st_mode):
                # governance-mutation: SHARED_CARD_WALK_FILE_MODE
                if info.st_nlink!=1 or info.st_mode&0o111:raise ValueError('ARTIFACT_LINK_OR_MODE_INVALID')
                if info.st_size>ev.MAX_FILE or not info.st_mode&0o444:raise ValueError('SOURCE_SIZE_OR_TYPE_INVALID')
                child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    if _stamp(info)!=_stamp(os.fstat(child)):raise ValueError('SOURCE_CHANGED_DURING_READ')
                    length=0;digest=hashlib.sha256()
                    while True:
                        raw=os.read(child,min(512*1024,ev.MAX_FILE+1-length))
                        if not raw:break
                        length+=len(raw)
                        if length>ev.MAX_FILE:raise ValueError('SOURCE_SIZE_OR_TYPE_INVALID')
                        digest.update(raw)
                    # governance-mutation: SHARED_CARD_WALK_READ_STABILITY
                    if length!=info.st_size or _stamp(info)!=_stamp(os.fstat(child)):
                        raise ValueError('SOURCE_CHANGED_DURING_READ')
                finally:os.close(child)
                total+=length;files[relative]=digest.hexdigest()
                if len(files)>256 or total>128*1024*1024:raise ValueError('ARTIFACT_LIMIT')
            else:raise ValueError('ARTIFACT_PATH_INVALID')
            if _stamp(info)!=_stamp(os.stat(name,dir_fd=fd,follow_symlinks=False)):
                raise ValueError('SOURCE_CHANGED_DURING_READ')
        if _stamp(before)!=_stamp(os.fstat(fd)):raise ValueError('SOURCE_CHANGED_DURING_READ')
        return bool(names)
    with materials._directory(root) as opened:
        before=os.fstat(opened);walk(opened)
        # Reopen the complete root path to reject swaps of any lexical ancestor.
        # governance-mutation: SHARED_CARD_WALK_ROOT_BINDING
        with materials._directory(root) as reopened:
            if _stamp(before)!=_stamp(os.fstat(reopened)):raise ValueError('SOURCE_CHANGED_DURING_READ')
    return files,total
