"""Original-byte credential dispatch must preserve the full string predicate."""
import hashlib
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/llm'))
import foundation_materials as materials
import workbench_snapshot_brief as brief
import team_ai_workspace as team


def dispatch(raw):
    # The unchanged baseline is a real predicate, not a missing-import failure.
    helper=getattr(brief,'reject_latin1_credentials',None)
    return helper(raw) if helper is not None else brief.reject_credentials(raw.decode('latin-1'))


def outcome(fn):
    try:fn()
    except brief.SnapshotBriefError:return 'REFUSED'
    return 'ACCEPTED'


def full_calls(callback):
    reference=brief.reject_credentials.__code__;calls=[];previous=sys.getprofile()
    def observed(frame,event,_value):
        if event=='call' and frame.f_code is reference:calls.append(None)
    try:
        sys.setprofile(observed);value=callback()
    finally:sys.setprofile(previous)
    return value,len(calls)


class Latin1CredentialScanTests(unittest.TestCase):
    def same(self,raw):
        self.assertEqual(outcome(lambda:dispatch(raw)),
                         outcome(lambda:brief.reject_credentials(raw.decode('latin-1'))))

    def test_benign_original_window_avoids_full_conversion(self):
        raw=b'%PDF-1.7\n'+bytes(range(256))*128
        _value,count=full_calls(lambda:dispatch(raw))
        self.assertEqual(count,0,'Impossible binary candidate entered full string conversion')

    def test_benign_stream_retains_hash_without_full_conversion(self):
        raw=b'%PDF-1.7\n'+b'q\xfeZ78b&!\xa0=i'*(materials.CHUNK_BYTES//10+200)
        with tempfile.TemporaryFile() as stream:
            stream.write(raw);stream.seek(0)
            checksum,count=full_calls(lambda:materials._stream(stream.fileno(),size=len(raw),suffix='.pdf'))
        self.assertEqual(checksum,hashlib.sha256(raw).hexdigest())
        self.assertEqual(count,0,'Every benign original chunk still converts to a string')

    def test_reference_all_single_bytes_and_deterministic_binary_windows(self):
        for value in range(256):self.same(bytes([value]))
        rng=random.Random(1730)
        for _ in range(256):self.same(rng.randbytes(rng.randrange(0,1024)))

    def test_reference_credentials_escapes_boundaries_and_latin1_whitespace(self):
        suffix=b'A'*24
        corpus=[b'sk-'+suffix,b'ghp_'+suffix,b'github_pat_'+suffix,
          b'-----BEGIN RSA PRIVATE KEY-----',b'APP_TOKEN="'+suffix+b'"',
          b'prefix\\napp_password="'+suffix+b'"',b'client_secret="'+suffix+b'"',
          b'Authorization:\\tBearer '+suffix,b'bEaReR\x85'+suffix,b'bearer\xa0'+suffix,
          b'sk-'+b'A'*12,b'AKIA'+b'A'*16,b'Bearer tiny',b'api_key="short"']
        for raw in corpus:
            for prefix in [b'',b' ',b'X',b'\xe9',b'\xff ',b'\\r']:
                with self.subTest(prefix=prefix,example=raw[:12]):self.same(prefix+raw+b'\n')

    def test_latin1_input_is_not_reinterpreted_as_utf8(self):
        raw='\u017fk-'.encode()+b'A'*12
        self.assertEqual(outcome(lambda:dispatch(raw)),'ACCEPTED')
        with self.assertRaises(brief.SnapshotBriefError):brief.reject_credentials(raw.decode('utf-8'))

    def test_possible_candidate_delegates_to_unchanged_full_predicate(self):
        raw=b'bearer '+b'A'*24
        with mock.patch.object(brief,'reject_credentials',side_effect=ValueError('AUTHORITATIVE_FULL_SCAN')):
            with self.assertRaisesRegex(ValueError,'AUTHORITATIVE_FULL_SCAN'):dispatch(raw)

    def test_changed_full_detector_delegates_even_without_old_hints(self):
        with mock.patch.object(brief,'reject_credentials',side_effect=ValueError('NEW_FULL_POLICY')):
            with self.assertRaisesRegex(ValueError,'NEW_FULL_POLICY'):dispatch(b'benign original')

    def test_no_hint_rule_always_uses_full_predicate(self):
        extra=(re.compile(r'\bsvc_[A-Z0-9]{16}\b'),None)
        with mock.patch.object(brief,'_BRIEF_CREDENTIAL_RULES',brief._BRIEF_CREDENTIAL_RULES+(extra,)):
            with self.assertRaises(brief.SnapshotBriefError):dispatch(b'svc_'+b'A'*16)

    def test_unknown_iterable_policy_is_not_consumed_before_full_detection(self):
        extra=(re.compile(r'\bsvc_[A-Z0-9]{16}\b'),None)
        with mock.patch.object(brief,'_BRIEF_CREDENTIAL_RULES',iter((extra,))):
            with self.assertRaises(brief.SnapshotBriefError):dispatch(b'svc_'+b'A'*16)

    def test_non_ascii_repository_hint_uses_full_utf8_predicate(self):
        marker='\xe9'.encode()
        pattern=re.compile(marker)
        rules=(('SYNTHETIC_NONASCII',pattern,(marker,)),)
        with mock.patch.object(team,'_SECRET_RULES',rules),mock.patch.object(team,'_SECRET_BYTE_LITERALS',(marker,)),\
             mock.patch.object(team,'_SECRET_FOLDED_LITERALS',()),mock.patch.object(team,'_SECRET_UNFILTERED',False),\
             mock.patch.object(brief,'SECRET_PATTERNS',(('SYNTHETIC_NONASCII',pattern),)):
            with self.assertRaises(brief.SnapshotBriefError):dispatch(b'\xe9')

    def test_control_hint_created_by_decoding_escape_uses_full_predicate(self):
        marker=b'\nMARKER';pattern=re.compile(marker)
        rules=(('SYNTHETIC_CONTROL',pattern,(marker,)),)
        with mock.patch.object(team,'_SECRET_RULES',rules),mock.patch.object(team,'_SECRET_BYTE_LITERALS',(marker,)),\
             mock.patch.object(team,'_SECRET_FOLDED_LITERALS',()),mock.patch.object(team,'_SECRET_UNFILTERED',False),\
             mock.patch.object(brief,'SECRET_PATTERNS',(('SYNTHETIC_CONTROL',pattern),)):
            with self.assertRaises(brief.SnapshotBriefError):dispatch(b'prefix\\nMARKER')

    def test_unsynchronized_catalog_delegates_instead_of_assuming_no_match(self):
        extra=('SYNTHETIC_NEW_RULE',re.compile(b'UNLISTED'))
        with mock.patch.object(brief,'SECRET_PATTERNS',brief.SECRET_PATTERNS+(extra,)):
            _value,count=full_calls(lambda:dispatch(b'benign original'))
        self.assertEqual(count,1)

    def test_new_printable_hint_policy_also_delegates(self):
        extra=(re.compile(r'\bsvc_[A-Z0-9]{16}\b'),b'svc_')
        with mock.patch.object(brief,'_BRIEF_CREDENTIAL_RULES',brief._BRIEF_CREDENTIAL_RULES+(extra,)):
            _value,count=full_calls(lambda:dispatch(b'benign original'))
        self.assertEqual(count,1)

    def test_derived_repository_prefilter_state_change_delegates(self):
        with mock.patch.object(team,'_SECRET_FOLDED_LITERALS',team._SECRET_FOLDED_LITERALS+(b'UNLISTED',)):
            _value,count=full_calls(lambda:dispatch(b'benign original'))
        self.assertEqual(count,1)

    def test_non_ascii_brief_hint_uses_full_predicate(self):
        extra=(re.compile('\xe9'), '\xe9'.encode())
        with mock.patch.object(brief,'_BRIEF_CREDENTIAL_RULES',brief._BRIEF_CREDENTIAL_RULES+(extra,)):
            with self.assertRaises(brief.SnapshotBriefError):dispatch(b'\xe9')

    def test_metadata_change_and_new_window_are_rechecked_on_each_call(self):
        dispatch(b'benign original')
        extra=(re.compile('MUST_CHECK'),None)
        with mock.patch.object(brief,'_BRIEF_CREDENTIAL_RULES',brief._BRIEF_CREDENTIAL_RULES+(extra,)):
            with self.assertRaises(brief.SnapshotBriefError):dispatch(b'MUST_CHECK')
        with self.assertRaises(brief.SnapshotBriefError):dispatch(b'bearer '+b'A'*24)

    def test_stream_overlap_keeps_candidate_across_chunk_boundary(self):
        raw=b'%PDF-1.7\n'
        raw+=b' '*(materials.CHUNK_BYTES-len(raw)-3)+b'bea'+b'rer '+b'A'*24
        with tempfile.TemporaryFile() as stream:
            stream.write(raw);stream.seek(0)
            with self.assertRaises(brief.SnapshotBriefError):
                materials._stream(stream.fileno(),size=len(raw),suffix='.pdf')

    def test_json_escaped_credential_still_reaches_final_structured_check(self):
        raw=b'{"payload":"s\\u006b-'+b'A'*12+b'"}'
        with tempfile.TemporaryFile() as stream:
            stream.write(raw);stream.seek(0)
            with self.assertRaises(brief.SnapshotBriefError):
                materials._stream(stream.fileno(),size=len(raw),suffix='.json')


if __name__=='__main__':unittest.main()
