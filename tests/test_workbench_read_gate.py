"""Bounded, fair proof admission without cached data or blocked context reads."""
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts/llm'),str(ROOT)]
from workbench_read_gate import ReadGate,verified_read
from workbench_workspace import WorkspaceError


class ReadGateTests(unittest.TestCase):
    def waiters(self,gate,count):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with gate._condition:
                if len(gate._waiting)==count:return
            time.sleep(.001)
        self.fail('read admission did not reach the expected queue')

    def test_serial_fifo_reentrant_and_exception_release(self):
        gate=ReadGate();order=[];errors=[];threads=[]
        def read(i):
            try:
                with gate.acquire():
                    with gate.acquire():order.append(i)
                    if i==1:raise ValueError('EXPECTED_PROOF_REJECTION')
            except ValueError:errors.append(i)
        with gate.acquire():
            for i in range(3):
                thread=threading.Thread(target=read,args=(i,));threads.append(thread);thread.start()
                self.waiters(gate,i+1)
            self.assertEqual(order,[],'a nested owner must not admit another thread')
        for thread in threads:thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(order,[0,1,2]);self.assertEqual(errors,[1])
        with gate.acquire():pass

    def test_timeout_removes_waiter_and_allows_future_reads(self):
        gate=ReadGate(wait_seconds=.03);errors=[];finished=threading.Event()
        def read():
            try:
                with gate.acquire():pass
            except WorkspaceError as error:errors.append(error)
            finally:finished.set()
        with gate.acquire():
            thread=threading.Thread(target=read);thread.start()
            timed_out=finished.wait(.3)
        thread.join(1)
        self.assertTrue(timed_out,'waiting must be bounded before owner release')
        self.assertEqual([str(e) for e in errors],['SHARED_VERIFIED_READ_BUSY'])
        self.assertEqual(errors[0].status,429)
        with gate.acquire():pass
        self.assertEqual(len(gate._waiting),0)

    def test_expired_waiter_cannot_enter_when_owner_becomes_free(self):
        gate=ReadGate(wait_seconds=.02);clock=[0.0];waiting=threading.Event();outcome=[]
        original=gate._condition.wait
        def wait(timeout=None):waiting.set();return original(timeout)
        def read():
            try:
                with gate.acquire():outcome.append('ADMITTED')
            except WorkspaceError as error:outcome.append(str(error))
        with patch('workbench_read_gate.time.monotonic',side_effect=lambda:clock[0]),\
                patch.object(gate._condition,'wait',side_effect=wait):
            lease=gate.acquire();lease.__enter__();thread=threading.Thread(target=read);thread.start()
            try:
                self.assertTrue(waiting.wait(1))
                with gate._condition:
                    clock[0]=1.0;lease.__exit__(None,None,None)
            finally:
                if gate._owner==threading.get_ident():lease.__exit__(None,None,None)
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome,['SHARED_VERIFIED_READ_BUSY'])
            self.assertEqual(len(gate._waiting),0)
            with gate.acquire():pass

    def test_capacity_refuses_without_displacing_existing_waiter(self):
        gate=ReadGate(max_waiters=1);order=[]
        def read():
            with gate.acquire():order.append('first')
        with gate.acquire():
            thread=threading.Thread(target=read);thread.start();self.waiters(gate,1)
            errors=[]
            def rejected():
                try:
                    with gate.acquire():order.append('unexpected')
                except WorkspaceError as error:errors.append(error)
            second=threading.Thread(target=rejected);second.start();second.join(.3)
            refused=not second.is_alive()
        thread.join(2);second.join(2)
        self.assertTrue(refused);self.assertEqual(order,['first'])
        self.assertEqual([str(e) for e in errors],['SHARED_VERIFIED_READ_BUSY'])

    def test_identity_checked_before_queue_and_again_inside_original_reader(self):
        gate=ReadGate();calls=[]
        class Reader:
            _read_gate=gate
            def identity(self,actor):
                calls.append(actor)
                if actor!='allowed':raise WorkspaceError('DENIED',403)
            @verified_read(actor_position=1)
            def detail(self,job,actor):
                self.identity(actor)
                return {'job':job,'actor':actor}
        reader=Reader()
        with self.assertRaisesRegex(WorkspaceError,'DENIED'):reader.detail('j','revoked')
        self.assertEqual(len(gate._waiting),0)
        self.assertEqual(reader.detail('j',actor='allowed'),{'job':'j','actor':'allowed'})
        self.assertEqual(calls,['revoked','allowed','allowed'])

    def test_configuration_cannot_expand_default_caps(self):
        for kwargs in ({'max_waiters':True},{'max_waiters':0},{'max_waiters':9},
                       {'wait_seconds':False},{'wait_seconds':0},{'wait_seconds':16},
                       {'wait_seconds':float('nan')},{'wait_seconds':float('inf')}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ReadGate(**kwargs)


if __name__=='__main__':unittest.main()
