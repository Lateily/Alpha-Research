"""Full PDF graphs stay audited when repeated immutable leaves share a budget."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts/llm'), str(Path(__file__).resolve().parent)]
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject
import foundation_research as research
import foundation_materials as materials
from test_foundation_research import pdf_bytes


def reader(value):
    return SimpleNamespace(trailer=value, xref={}, xref_objStm={}, get_object=lambda ref: NumberObject(1))


class AnnualPdfSafetyTests(unittest.TestCase):
    def audit(self, value):
        self.assertTrue(hasattr(research, '_audit_pdf_objects'), 'bounded full-graph audit helper missing')
        return research._audit_pdf_objects(value)

    def test_repeated_names_and_integers_do_not_spend_distinct_node_budget(self):
        graph = ArrayObject([DictionaryObject({NameObject('/Type'): NameObject('/Glyph'),
                 NameObject('/Width'): NumberObject(500), NameObject('/Index'): NumberObject(0)}) for _ in range(1000)])
        with mock.patch.object(research, 'MAX_PDF_OBJECTS', 1500, create=True):
            try:
                receipt = self.audit(reader(graph))
            except ValueError as exc:
                self.fail('Repeated childless constants were falsely refused: ' + str(exc))
        self.assertLess(receipt['nodes'], 1500)
        self.assertGreater(receipt['visits'], receipt['nodes'])

    def test_distinct_objects_still_hit_the_original_node_limit(self):
        graph = ArrayObject([TextStringObject(str(i)) for i in range(5)])
        with mock.patch.object(research, 'MAX_PDF_OBJECTS', 6, create=True):
            self.assertEqual(self.audit(reader(graph))['nodes'], 6)
        with mock.patch.object(research, 'MAX_PDF_OBJECTS', 5, create=True):
            with self.assertRaisesRegex(ValueError, 'PDF_OBJECT_LIMIT'): self.audit(reader(graph))

    def test_duplicate_edge_bomb_is_refused_before_queue_expansion(self):
        class NoExpansion(ArrayObject):
            def __iter__(self):
                raise AssertionError('unbounded queue was expanded before refusal')
        graph = NoExpansion([NumberObject(0)] * 200)
        with mock.patch.object(research, 'MAX_PDF_VISITS', 128, create=True):
            with self.assertRaisesRegex(ValueError, 'PDF_VISIT_LIMIT'): self.audit(reader(graph))

    def test_indirect_seed_inventory_is_bounded_even_when_decoded_values_repeat(self):
        value = reader(DictionaryObject()); value.xref = {0: {i: 0 for i in range(1, 130)}}
        opened = []
        def decode(ref):
            opened.append(ref.idnum)
            return NumberObject(1)
        value.get_object = decode
        with mock.patch.object(research, 'MAX_PDF_OBJECTS', 128, create=True):
            with self.assertRaisesRegex(ValueError, 'PDF_REFERENCE_LIMIT'): self.audit(value)
        self.assertEqual(opened, [])

    def test_active_name_after_duplicate_constants_is_always_refused(self):
        graph = ArrayObject([NameObject('/Type')] * 200 + [NameObject('/JS')])
        with self.assertRaisesRegex(ValueError, 'PDF_ACTIVE_CONTENT'): self.audit(reader(graph))

    def test_escaped_active_name_in_orphan_object_is_not_hidden_by_page_selection(self):
        class EscapedName(NameObject):
            def write_to_stream(self, stream, encryption_key=None):
                stream.write(str(self).replace('JavaScript', 'Java#53cript').replace('/JS', '/#4A#53').encode())
        writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes()))
        writer._add_object(DictionaryObject({NameObject('/S'): EscapedName('/JavaScript'),
                                             EscapedName('/JS'): TextStringObject('void(0)')}))
        stream = io.BytesIO(); writer.write(stream); raw = stream.getvalue()
        self.assertIsNone(materials.ACTIVE_PDF.search(raw))
        with self.assertRaises(ValueError): research._extract_child(raw, [1])

    def test_cyclic_direct_graph_terminates_without_skipping_other_nodes(self):
        graph = ArrayObject(); graph.append(graph); graph.append(NameObject('/Safe'))
        result = self.audit(reader(graph))
        self.assertEqual(result['nodes'], 2)
        self.assertEqual(result['visits'], 3)


if __name__ == '__main__':
    unittest.main()
