import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator, ValidationError
from control.context_ledger_publisher_contract import HistoricalLedgerPublishError, validate_request
from control.historical_claim_contract import CLAIMS_PATH, CONFLICTS_PATH, git_blob_sha
from control.historical_knowledge_importer import DEFAULT_SOURCE_SELECTORS, HistoricalImportError, PRODUCT_COMMIT, PRODUCT_REPOSITORY, ResolvedRevision, build_publication_request, default_corpus_evidence, freeze_records, generate_ledger, import_frozen_records
COMMIT = 'a' * 40
BASE = 'b' * 40

def resolver_from(mapping):

    def resolve(repository, commit, path):
        value = mapping.get((repository, commit, path), [])
        if isinstance(value, bytes):
            value = [value]
        return [item if isinstance(item, ResolvedRevision) else ResolvedRevision(repository, commit, path, item) for item in value]
    return resolve

def selector(key, source_class, path, data, *, line=1, text=None, status='supported', relations=None, subject=None, predicate='fact', commit=COMMIT, blob_sha=None):
    lines = data.decode('utf-8').splitlines()
    if text is None and 1 <= line <= len(lines):
        text = lines[line - 1]
    return {'record_key': key, 'source_class': source_class, 'repository': 'Example/history', 'commit': commit, 'path': path, 'locator': {'kind': 'line_range', 'start_line': line, 'end_line': line}, 'expected_blob_sha': blob_sha or git_blob_sha(data), 'expected_text': text or 'missing', 'subject': subject or f'history:{key}', 'predicate': predicate, 'status': status, 'validity': {'valid_from': '2026-08-13T00:00:00Z', 'valid_until': None}, 'relations': relations or {'supersedes': [], 'superseded_by': [], 'conflicts_with': []}}

def two_basic(*, status_a='supported', status_b='supported'):
    a = b'first changelog fact\n'
    b = b'first specification fact\n'
    selectors = [selector('a', 'changelog', 'changelog.md', a, status=status_a), selector('b', 'specification_history', 'SPEC_HISTORY.md', b, status=status_b)]
    mapping = {('Example/history', COMMIT, 'changelog.md'): a, ('Example/history', COMMIT, 'SPEC_HISTORY.md'): b}
    return (selectors, resolver_from(mapping))

class HistoricalKnowledgeImporterTests(unittest.TestCase):

    def test_exact_changelog_and_specification_history_extraction(self):
        selectors, resolver = two_basic()
        frozen, claims, outputs = generate_ledger(selectors, resolver)
        self.assertEqual([x['source_class'] for x in frozen], ['changelog', 'specification_history'])
        self.assertEqual({x['value'] for x in claims}, {'first changelog fact', 'first specification fact'})
        self.assertEqual(set(outputs), {CLAIMS_PATH, CONFLICTS_PATH})

    def test_deterministic_claim_id_and_exact_provenance_binding(self):
        selectors, resolver = two_basic()
        frozen1, claims1, outputs1 = generate_ledger(selectors, resolver)
        frozen2, claims2, outputs2 = generate_ledger(list(reversed(selectors)), resolver)
        self.assertEqual(frozen1, frozen2)
        self.assertEqual(claims1, claims2)
        self.assertEqual(outputs1, outputs2)
        for claim in claims1:
            self.assertRegex(claim['claim_id'], '^hc1-[0-9a-f]{64}$')
            self.assertEqual(claim['provenance']['commit'], COMMIT)
            self.assertRegex(claim['provenance']['content_sha256'], '^[0-9a-f]{64}$')

    def test_supported_and_unverified_classification_is_explicit(self):
        selectors, resolver = two_basic(status_a='supported', status_b='unverified')
        _, claims, _ = generate_ledger(selectors, resolver)
        self.assertEqual({x['status'] for x in claims}, {'supported', 'unverified'})
        unverified = next((x for x in claims if x['status'] == 'unverified'))
        self.assertEqual(unverified['relations'], {'supersedes': [], 'superseded_by': [], 'conflicts_with': []})

    def test_contradiction_is_preserved_and_symmetric_with_canonical_index(self):
        a = b'alpha\n'
        b = b'beta\n'
        selectors = [selector('a', 'changelog', 'a.md', a, status='contradicted', subject='history:x', relations={'supersedes': [], 'superseded_by': [], 'conflicts_with': ['b']}), selector('b', 'specification_history', 'b.md', b, status='contradicted', subject='history:x', relations={'supersedes': [], 'superseded_by': [], 'conflicts_with': ['a']})]
        resolver = resolver_from({('Example/history', COMMIT, 'a.md'): a, ('Example/history', COMMIT, 'b.md'): b})
        _, claims, outputs = generate_ledger(selectors, resolver)
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0]['relations']['conflicts_with'], [claims[1]['claim_id']])
        self.assertEqual(claims[1]['relations']['conflicts_with'], [claims[0]['claim_id']])
        index = json.loads(outputs[CONFLICTS_PATH])
        self.assertEqual(index['schema'], 'hwm-historical-conflicts/v1')
        self.assertEqual(len(index['conflicts']), 1)
        self.assertEqual(index['conflicts'][0]['claim_ids'], sorted([x['claim_id'] for x in claims]))

    def test_supersession_retains_old_evidence_bidirectionally(self):
        old = b'old rule\n'
        new = b'new rule\n'
        selectors = [selector('old', 'changelog', 'old.md', old, status='superseded', subject='history:rule', relations={'supersedes': [], 'superseded_by': ['new'], 'conflicts_with': []}), selector('new', 'specification_history', 'new.md', new, status='supported', subject='history:rule', relations={'supersedes': ['old'], 'superseded_by': [], 'conflicts_with': []})]
        resolver = resolver_from({('Example/history', COMMIT, 'old.md'): old, ('Example/history', COMMIT, 'new.md'): new})
        _, claims, _ = generate_ledger(selectors, resolver)
        self.assertEqual(len(claims), 2)
        old_claim = next((x for x in claims if x['status'] == 'superseded'))
        new_claim = next((x for x in claims if x['status'] == 'supported'))
        self.assertEqual(old_claim['relations']['superseded_by'], [new_claim['claim_id']])
        self.assertEqual(new_claim['relations']['supersedes'], [old_claim['claim_id']])

    def test_exact_duplicate_collapses_only_after_serialized_equality(self):
        selectors, resolver = two_basic()
        _, claims_a, outputs_a = generate_ledger(selectors, resolver)
        _, claims_b, outputs_b = generate_ledger(selectors + [copy.deepcopy(selectors[0])], resolver)
        self.assertEqual(claims_a, claims_b)
        self.assertEqual(outputs_a, outputs_b)

    def test_inconsistent_duplicate_record_key_fails(self):
        selectors, resolver = two_basic()
        bad = copy.deepcopy(selectors[0])
        bad['predicate'] = 'different'
        with self.assertRaisesRegex(HistoricalImportError, 'record_key'):
            freeze_records(selectors + [bad], resolver)

    def test_same_claim_id_with_unequal_serialization_fails(self):
        data = b'same literal\n'
        base = selector('a', 'changelog', 'same.md', data, subject='history:same')
        other = copy.deepcopy(base)
        other['record_key'] = 'b'
        other['source_class'] = 'specification_history'
        other['status'] = 'unverified'
        resolver = resolver_from({('Example/history', COMMIT, 'same.md'): data})
        with self.assertRaisesRegex(HistoricalImportError, 'same claim_id'):
            generate_ledger([base, other], resolver)

    def test_symbolic_or_guessed_head_is_rejected(self):
        selectors, resolver = two_basic()
        selectors[0]['commit'] = 'HEAD'
        with self.assertRaisesRegex(HistoricalImportError, 'exact lowercase 40-hex'):
            freeze_records(selectors, resolver)

    def test_missing_commit_path_or_blob_fails_closed(self):
        selectors, _ = two_basic()
        for field in ('commit', 'path', 'expected_blob_sha'):
            bad = copy.deepcopy(selectors)
            del bad[0][field]
            with self.subTest(field=field), self.assertRaises(HistoricalImportError):
                freeze_records(bad, resolver_from({}))

    def test_missing_and_ambiguous_revision_fail_closed(self):
        selectors, _ = two_basic()
        with self.assertRaisesRegex(HistoricalImportError, 'missing'):
            freeze_records(selectors, resolver_from({}))
        a_data = b'first changelog fact\n'
        b_data = b'first specification fact\n'
        amb = {('Example/history', COMMIT, 'changelog.md'): [ResolvedRevision('Example/history', COMMIT, 'changelog.md', a_data), ResolvedRevision('Example/history', COMMIT, 'changelog.md', a_data)], ('Example/history', COMMIT, 'SPEC_HISTORY.md'): b_data}
        with self.assertRaisesRegex(HistoricalImportError, 'ambiguous'):
            freeze_records(selectors, resolver_from(amb))

    def test_stale_provenance_and_invalid_locator_fail_closed(self):
        selectors, resolver = two_basic()
        a_data = b'first changelog fact\n'
        b_data = b'first specification fact\n'
        mismatched = resolver_from({('Example/history', COMMIT, 'changelog.md'): [ResolvedRevision('Example/history', 'c' * 40, 'changelog.md', a_data)], ('Example/history', COMMIT, 'SPEC_HISTORY.md'): b_data})
        with self.assertRaisesRegex(HistoricalImportError, 'stale or mismatched'):
            freeze_records(selectors, mismatched)
        stale = copy.deepcopy(selectors)
        stale[0]['locator'] = {'kind': 'line_range', 'start_line': 9, 'end_line': 9}
        stale[0]['expected_text'] = 'invented'
        with self.assertRaisesRegex(HistoricalImportError, 'stale or missing'):
            freeze_records(stale, resolver)
        bad_locator = copy.deepcopy(selectors)
        bad_locator[0]['locator'] = {'kind': 'symbol', 'symbol': 'guess'}
        with self.assertRaisesRegex(HistoricalImportError, 'line_range'):
            freeze_records(bad_locator, resolver)

    def test_git_blob_mismatch_fails_closed(self):
        selectors, resolver = two_basic()
        selectors[0]['expected_blob_sha'] = 'f' * 40
        with self.assertRaisesRegex(HistoricalImportError, 'Git blob mismatch'):
            freeze_records(selectors, resolver)

    def test_content_sha256_mismatch_fails_closed(self):
        selectors, resolver = two_basic()
        frozen = freeze_records(selectors, resolver)
        frozen[0]['content_sha256'] = '0' * 64
        with self.assertRaisesRegex(HistoricalImportError, 'content SHA-256 mismatch'):
            import_frozen_records(frozen, resolver)

    def test_one_sided_conflict_and_dangling_supersession_fail(self):
        a = b'alpha\n'
        b = b'beta\n'
        resolver = resolver_from({('Example/history', COMMIT, 'a.md'): a, ('Example/history', COMMIT, 'b.md'): b})
        one_sided = [selector('a', 'changelog', 'a.md', a, status='contradicted', relations={'supersedes': [], 'superseded_by': [], 'conflicts_with': ['b']}), selector('b', 'specification_history', 'b.md', b, status='contradicted')]
        with self.assertRaises(HistoricalImportError):
            generate_ledger(one_sided, resolver)
        dangling = copy.deepcopy(one_sided)
        dangling[0]['status'] = 'supported'
        dangling[0]['relations'] = {'supersedes': ['missing'], 'superseded_by': [], 'conflicts_with': []}
        with self.assertRaisesRegex(HistoricalImportError, 'dangling'):
            generate_ledger(dangling, resolver)

    def test_contradiction_cannot_be_silently_collapsed(self):
        a = b'alpha\n'
        b = b'beta\n'
        selectors = [selector('a', 'changelog', 'a.md', a, status='contradicted', subject='history:x', relations={'supersedes': [], 'superseded_by': [], 'conflicts_with': ['b']}), selector('b', 'specification_history', 'b.md', b, status='contradicted', subject='history:x', relations={'supersedes': [], 'superseded_by': [], 'conflicts_with': ['a']})]
        resolver = resolver_from({('Example/history', COMMIT, 'a.md'): a, ('Example/history', COMMIT, 'b.md'): b})
        _, claims, _ = generate_ledger(selectors, resolver)
        self.assertEqual(len(claims), 2)
        self.assertNotEqual(claims[0]['claim_id'], claims[1]['claim_id'])

    def test_unverified_is_never_implicitly_promoted(self):
        selectors, resolver = two_basic(status_b='unverified')
        frozen = freeze_records(selectors, resolver)
        claims = import_frozen_records(frozen, resolver)
        spec = next((x for x in claims if x['provenance']['source_class'] == 'specification_history'))
        self.assertEqual(spec['status'], 'unverified')

    def test_current_state_override_attempt_fails(self):
        selectors, resolver = two_basic()
        selectors[0]['subject'] = 'current:product-head'
        with self.assertRaises(HistoricalImportError):
            generate_ledger(selectors, resolver)
        selectors, resolver = two_basic()
        selectors[0]['predicate'] = 'current.product_head'
        with self.assertRaises(HistoricalImportError):
            generate_ledger(selectors, resolver)

    def test_hwm_claim_v1_is_rejected_as_historical_record_shape(self):
        selectors, resolver = two_basic()
        selectors[0]['schema'] = 'hwm-claim/v1'
        with self.assertRaisesRegex(HistoricalImportError, 'hwm-claim/v1'):
            freeze_records(selectors, resolver)

    def test_nondeterministic_input_order_cannot_change_output(self):
        selectors, resolver = two_basic()
        _, _, out_a = generate_ledger(selectors, resolver)
        _, _, out_b = generate_ledger(list(reversed(selectors)), resolver)
        self.assertEqual(out_a[CLAIMS_PATH], out_b[CLAIMS_PATH])
        self.assertEqual(out_a[CONFLICTS_PATH], out_b[CONFLICTS_PATH])

    def test_trusted_publication_request_is_exact_two_path_and_idempotent(self):
        outputs = {CLAIMS_PATH: '1' * 40, CONFLICTS_PATH: '2' * 40}
        request = build_publication_request(request_id='I08-0038-test-publication', expected_base=BASE, publication_branch='publisher/historical-ledger/i08-0038-test-publication', output_blob_shas=outputs)
        self.assertIsNotNone(request)
        self.assertEqual({x['path'] for x in request['changes']}, {CLAIMS_PATH, CONFLICTS_PATH})
        self.assertIsNone(build_publication_request(request_id='I08-0038-test-replay', expected_base=BASE, publication_branch='publisher/historical-ledger/i08-0038-test-replay', output_blob_shas=outputs, existing_blob_shas=outputs))

    def test_unauthorized_context_path_and_direct_protected_target_are_rejected(self):
        with self.assertRaises(HistoricalImportError):
            build_publication_request(request_id='I08-0038-bad-path', expected_base=BASE, publication_branch='publisher/historical-ledger/i08-0038-bad-path', output_blob_shas={CLAIMS_PATH: '1' * 40, 'state/current.json': '2' * 40})
        request = build_publication_request(request_id='I08-0038-bad-main', expected_base=BASE, publication_branch='publisher/historical-ledger/i08-0038-bad-main', output_blob_shas={CLAIMS_PATH: '1' * 40, CONFLICTS_PATH: '2' * 40})
        request['publication_branch'] = 'main'
        with self.assertRaises(HistoricalLedgerPublishError):
            validate_request(request)

    def test_knowledge_delta_is_valid_and_invalid_shape_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / 'schemas' / 'knowledge-delta.v1.schema.json').read_text(encoding='utf-8'))
        validator = Draft202012Validator(schema)
        kd = json.loads((root / 'knowledge-deltas' / 'I08-0038.json').read_text(encoding='utf-8'))
        validator.validate(kd)
        with self.assertRaises(ValidationError):
            validator.validate({})

    @unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true', 'exact public Git corpus integration runs in GitHub CI')
    def test_default_exact_git_corpus_is_schema_valid_and_byte_identical(self):
        evidence = default_corpus_evidence()
        frozen = evidence['frozen_records']
        self.assertEqual({x['source_class'] for x in frozen}, {'changelog', 'specification_history'})
        self.assertEqual(frozen[0]['repository'], PRODUCT_REPOSITORY)
        self.assertEqual(frozen[0]['commit'], PRODUCT_COMMIT)
        self.assertEqual(frozen[0]['literal_value'], DEFAULT_SOURCE_SELECTORS[0]['expected_text'])
        self.assertEqual(frozen[1]['literal_value'], DEFAULT_SOURCE_SELECTORS[1]['expected_text'])
        root = Path(__file__).resolve().parents[1]
        claim_schema = json.loads((root / 'schemas' / 'historical-claim.v1.schema.json').read_text(encoding='utf-8'))
        conflict_schema = json.loads((root / 'schemas' / 'historical-conflicts.v1.schema.json').read_text(encoding='utf-8'))
        claim_validator = Draft202012Validator(claim_schema)
        for claim in evidence['claims']:
            claim_validator.validate(claim)
        conflicts_bytes = base64.b64decode(evidence['outputs'][CONFLICTS_PATH]['base64'])
        Draft202012Validator(conflict_schema).validate(json.loads(conflicts_bytes))
        print('I08_FROZEN_CORPUS=' + json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        for path, prefix in ((CLAIMS_PATH, 'I08_CLAIMS'), (CONFLICTS_PATH, 'I08_CONFLICTS')):
            item = evidence['outputs'][path]
            data = base64.b64decode(item['base64'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['content_sha256'])
            self.assertEqual(git_blob_sha(data), item['git_blob_sha'])
            print(prefix + '_GIT_BLOB_SHA=' + item['git_blob_sha'])
            print(prefix + '_SHA256=' + item['content_sha256'])
            print(prefix + '_BASE64=' + item['base64'])
if __name__ == '__main__':
    unittest.main()
