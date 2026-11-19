"""Bounded FIFO admission for full read proofs; no retained proof or result."""
from collections import deque
from contextlib import contextmanager
from functools import wraps
import math
import threading
import time

from workbench_workspace import WorkspaceError


class ReadGate:
    def __init__(self, *, max_waiters=8, wait_seconds=15):
        if (type(max_waiters) is not int or not 1<=max_waiters<=8
                or type(wait_seconds) not in (int,float) or not math.isfinite(wait_seconds)
                or not 0<wait_seconds<=15):
            raise ValueError('READ_GATE_CONFIGURATION_INVALID')
        self._condition=threading.Condition()
        self._waiting=deque()
        self._owner=None
        self._depth=0
        self._max_waiters=max_waiters
        self._wait_seconds=wait_seconds

    @contextmanager
    def acquire(self):
        owner=threading.get_ident()
        with self._condition:
            if self._owner==owner:
                self._depth+=1
            else:
                if len(self._waiting)>=self._max_waiters:
                    raise WorkspaceError('SHARED_VERIFIED_READ_BUSY',429)
                ticket=object();self._waiting.append(ticket)
                deadline=time.monotonic()+self._wait_seconds
                try:
                    # governance-mutation: SHARED_READ_FIFO_ADMISSION
                    while self._owner is not None or self._waiting[0] is not ticket:
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise WorkspaceError('SHARED_VERIFIED_READ_BUSY',429)
                        self._condition.wait(remaining)
                    self._waiting.popleft();self._owner=owner;self._depth=1
                except BaseException:
                    self._waiting.remove(ticket);self._condition.notify_all()
                    raise
        try:
            yield
        finally:
            with self._condition:
                self._depth-=1
                if not self._depth:
                    self._owner=None;self._condition.notify_all()


def verified_read(method=None,*,actor_position=0):
    if method is None:
        return lambda function:verified_read(function,actor_position=actor_position)
    @wraps(method)
    def read(self,*args,**kwargs):
        actor=kwargs.get('actor',args[actor_position] if len(args)>actor_position else None)
        self.identity(actor)
        with self._read_gate.acquire():
            # Original methods still revalidate identity after waiting and all evidence.
            return method(self,*args,**kwargs)
    return read
