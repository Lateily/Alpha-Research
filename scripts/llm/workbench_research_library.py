"""Read-only pinned research metadata; never a content distribution endpoint."""
from pathlib import Path
import os

import foundation_materials as materials
import foundation_results as results
from workbench_workspace import WorkspaceError

SCHEMA = 'ar.shared-research-library.v1'
PAGE_SIZE = 50
FILTERS = ('industry_key', 'industry_taxonomy', 'taxonomy_version', 'research_date', 'ts_code')
ROW_FIELDS = ('material_id', 'version', 'company', 'industry_key', 'industry_taxonomy',
    'taxonomy_version', 'research_date', 'source_cutoff_at', 'artifact_generated_at',
    'archived_at', 'result_hash', 'pack_hash', 'record_hash', 'report_sha256',
    'consumer_execution_identity', 'importer_execution_identity', 'execution_attestation',
    'stored_verification', 'assessments', *results.LABELS)
SOURCE_FIELDS = ('material_id', 'version', 'pdf_sha256', 'published_at', 'available_at',
                 'captured_at', 'publisher_status')


def filters(values, page):
    try:
        if set(values) != set(FILTERS) or type(page) is not int or not 0 <= page <= 999:
            raise ValueError
        for key, value in values.items():
            if value is None: continue
            if key == 'research_date': materials._date(value)
            elif key == 'ts_code': materials._ticker(value)
            else: materials._identifier(value)
    except (ValueError, TypeError, KeyError):
        raise WorkspaceError('RESEARCH_LIBRARY_QUERY_INVALID', 400) from None


class ResearchLibrary:
    def __init__(self, root, expected_hash):
        self.root, self.expected_hash = Path(root), expected_hash
        self.read()

    def read(self, **query):
        try:
            with materials._directory(materials._root(self.root)) as fd:
                info = os.fstat(fd)
                # governance-mutation: SHARED_RESEARCH_LIBRARY_ROOT
                if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                    raise ValueError('operator library ownership or mode changed')
            # governance-mutation: SHARED_RESEARCH_LIBRARY_PIN
            return results.query_results(self.root, expected_library_hash=self.expected_hash, **query)
        except (ValueError, OSError, KeyError, TypeError, UnicodeError):
            raise WorkspaceError('RESEARCH_LIBRARY_EVIDENCE_INVALID', 409) from None


def projection(library, *, owner, code_sha, page=0, **query):
    filters(query, page)
    view = library.read(**query) if library is not None else None
    rows = []
    for row in view['results'] if view else []:
        # Whitelist metadata at both levels; future stored fields cannot leak content.
        # governance-mutation: SHARED_RESEARCH_LIBRARY_METADATA
        item = {key: row[key] for key in ROW_FIELDS}
        item['source_documents'] = []
        for source in row['source_documents']:
            doc = {key: source[key] for key in SOURCE_FIELDS}
            precision = source['publication_precision']
            doc['publication_precision'] = None if precision is None else {
                key: precision[key] for key in ('basis', 'published_on') if key in precision}
            item['source_documents'].append(doc)
        rows.append(item)
    return {'schema': SCHEMA, 'status': view['status'] if view else 'NOT_CONFIGURED',
        'library_hash': view['library_hash'] if view else None, 'query': query,
        'page': page, 'page_size': PAGE_SIZE, 'total': len(rows),
        'results': rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE],
        'my_workspace': owner, 'consumer_code_sha': code_sha,
        # governance-mutation: SHARED_RESEARCH_LIBRARY_CONTENT
        'content_sharing_allowed': False, 'content_status': 'RIGHTS_UNVERIFIED_CONTENT_DENIED',
        'rights': dict(materials.RIGHTS), **results.LABELS}
