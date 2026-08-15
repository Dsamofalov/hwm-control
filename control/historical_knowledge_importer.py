#!/usr/bin/env python3
"""Deterministic I08 historical knowledge importer (minimal Phase-6 slice)."""
from __future__ import annotations
from dataclasses import dataclass
import base64
import copy
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable, Mapping, Sequence
from control.context_ledger_publisher_contract import validate_request as validate_publish_request
from control.historical_claim_contract import CLAIMS_PATH, CONFLICTS_PATH, HistoricalClaimContractError, canonical_json, compute_claim_id, content_sha256, git_blob_sha, materialize_ledger, verify_source_binding
SHA40 = re.compile('^[0-9a-f]{40}$')
SHA64 = re.compile('^[0-9a-f]{64}$')
SOURCE_CLASSES = frozenset({'changelog', 'specification_history'})
STATUSES = frozenset({'supported', 'superseded', 'contradicted', 'unverified'})
RELATIONS = ('supersedes', 'superseded_by', 'conflicts_with')
MAX_SOURCE_BYTES = 1024 * 1024
PRODUCT_REPOSITORY = 'Dsamofalov/hwm_predictor'
PRODUCT_COMMIT = '8fd669336b36064e842252d69fb4016cc526a9d4'
DEFAULT_SOURCE_SELECTORS: tuple[dict[str, Any], ...] = ({'record_key': 'changelog-ability-main-governance', 'source_class': 'changelog', 'repository': PRODUCT_REPOSITORY, 'commit': PRODUCT_COMMIT, 'path': 'changelog.md', 'locator': {'kind': 'line_range', 'start_line': 16, 'end_line': 16}, 'expected_blob_sha': '40e1eac296094a7528d58bc4ec8734673619d866', 'expected_text': '- Ability is now a logical module/ownership boundary, not a dedicated Git development lane. All future ability implementation, evidence, tests, registry/risk updates and docs are committed directly to `main`.', 'subject': 'product:ability-development-governance', 'predicate': 'development_lane', 'status': 'supported', 'validity': {'valid_from': '2026-08-13T00:00:00Z', 'valid_until': None}, 'relations': {'supersedes': [], 'superseded_by': [], 'conflicts_with': []}}, {'record_key': 'spec-history-ability-main-governance', 'source_class': 'specification_history', 'repository': PRODUCT_REPOSITORY, 'commit': PRODUCT_COMMIT, 'path': 'ABILITY_MERGE_CANON.md', 'locator': {'kind': 'line_range', 'start_line': 5, 'end_line': 5}, 'expected_blob_sha': '61ad23b52b3115bea8bf67c5b1fb6b07932b6748', 'expected_text': '> Ability development no longer uses a dedicated `ability` source branch or a merge-back lane. The ability domain is a logical module and ownership boundary inside normal development on `main`.', 'subject': 'product:ability-development-governance', 'predicate': 'development_lane', 'status': 'supported', 'validity': {'valid_from': '2026-08-13T00:00:00Z', 'valid_until': None}, 'relations': {'supersedes': [], 'superseded_by': [], 'conflicts_with': []}})

class HistoricalImportError(ValueError):
    pass

@dataclass(frozen=True)
class ResolvedRevision:
    repository: str
    commit: str
    path: str
    source_bytes: bytes
    revision_candidates: int = 1
    resolved_symbols: tuple[str, ...] = ()
Resolver = Callable[[str, str, str], Sequence[ResolvedRevision]]

def _sha(value: Any, n: int, name: str) -> str:
    rx = SHA40 if n == 40 else SHA64
    if not isinstance(value, str) or rx.fullmatch(value) is None:
        raise HistoricalImportError(f'{name} must be an exact lowercase {n}-hex digest')
    return value

def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or value.startswith('/') or value.endswith('/') or any((x in {'', '.', '..'} for x in value.split('/'))):
        raise HistoricalImportError('source path must be exact and repository-relative')
    return value

def _locator(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {'kind', 'start_line', 'end_line'} or value.get('kind') != 'line_range':
        raise HistoricalImportError('minimal I08 slice requires exact line_range locator')
    a, b = (value['start_line'], value['end_line'])
    if not isinstance(a, int) or isinstance(a, bool) or (not isinstance(b, int)) or isinstance(b, bool) or (a < 1) or (b < a):
        raise HistoricalImportError('invalid exact line range')
    return {'kind': 'line_range', 'start_line': a, 'end_line': b}

def _rels(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping) or set(value) != set(RELATIONS):
        raise HistoricalImportError('invalid relation keys')
    out: dict[str, list[str]] = {}
    for name in RELATIONS:
        items = value[name]
        if not isinstance(items, list) or not all((isinstance(x, str) and x for x in items)) or len(items) != len(set(items)):
            raise HistoricalImportError(f'invalid {name} record keys')
        out[name] = sorted(items)
    return out

def _selector(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {'record_key', 'source_class', 'repository', 'commit', 'path', 'locator', 'expected_blob_sha', 'expected_text', 'subject', 'predicate', 'status', 'validity', 'relations'}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise HistoricalImportError('source selector shape mismatch; historical hwm-claim/v1 is forbidden')
    if raw['source_class'] not in SOURCE_CLASSES:
        raise HistoricalImportError('minimal slice supports only changelog and specification_history')
    if not isinstance(raw['record_key'], str) or not raw['record_key']:
        raise HistoricalImportError('record_key is required')
    if not isinstance(raw['repository'], str) or raw['repository'].count('/') != 1:
        raise HistoricalImportError('repository must be exact owner/name')
    if not isinstance(raw['expected_text'], str) or not raw['expected_text']:
        raise HistoricalImportError('expected_text must be literal and non-empty')
    if not isinstance(raw['subject'], str) or not raw['subject'] or (not isinstance(raw['predicate'], str)) or (not raw['predicate']):
        raise HistoricalImportError('subject/predicate must be explicit')
    if raw['status'] not in STATUSES:
        raise HistoricalImportError('invalid status')
    if not isinstance(raw['validity'], Mapping) or set(raw['validity']) != {'valid_from', 'valid_until'}:
        raise HistoricalImportError('validity must be explicit')
    return {**copy.deepcopy(dict(raw)), 'commit': _sha(raw['commit'], 40, 'commit'), 'path': _path(raw['path']), 'locator': _locator(raw['locator']), 'expected_blob_sha': _sha(raw['expected_blob_sha'], 40, 'expected_blob_sha'), 'relations': _rels(raw['relations'])}

def _dedupe(items: Iterable[Mapping[str, Any]], normalize: Callable[[Mapping[str, Any]], dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    serialized: dict[str, str] = {}
    for raw in items:
        item = normalize(raw)
        key = item[key_name]
        text = canonical_json(item)
        if key in by_key and serialized[key] != text:
            raise HistoricalImportError(f'{key_name} reused with incompatible serialization')
        if key not in by_key:
            by_key[key], serialized[key] = (item, text)
    return [by_key[k] for k in sorted(by_key)]

def _resolve(item: Mapping[str, Any], resolver: Resolver, blob_field: str) -> ResolvedRevision:
    found = list(resolver(item['repository'], item['commit'], item['path']))
    if not found:
        raise HistoricalImportError('source revision is missing')
    if len(found) != 1 or found[0].revision_candidates != 1:
        raise HistoricalImportError('source revision is ambiguous')
    rev = found[0]
    if (rev.repository, rev.commit, rev.path) != (item['repository'], item['commit'], item['path']):
        raise HistoricalImportError('source revision is stale or mismatched')
    if not isinstance(rev.source_bytes, bytes) or len(rev.source_bytes) > MAX_SOURCE_BYTES:
        raise HistoricalImportError('source blob unavailable or too large')
    if git_blob_sha(rev.source_bytes) != item[blob_field]:
        raise HistoricalImportError('Git blob mismatch')
    return rev

def _literal(data: bytes, loc: Mapping[str, Any]) -> str:
    try:
        lines = data.decode('utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise HistoricalImportError('source must be UTF-8') from exc
    if loc['end_line'] > len(lines):
        raise HistoricalImportError('exact locator is stale or missing')
    return '\n'.join(lines[loc['start_line'] - 1:loc['end_line']])

def freeze_records(selectors: Iterable[Mapping[str, Any]], resolver: Resolver) -> list[dict[str, Any]]:
    frozen = []
    for s in _dedupe(selectors, _selector, 'record_key'):
        rev = _resolve(s, resolver, 'expected_blob_sha')
        value = _literal(rev.source_bytes, s['locator'])
        if value != s['expected_text']:
            raise HistoricalImportError('literal locator mismatch; stale locator is never repaired')
        frozen.append({'record_key': s['record_key'], 'source_class': s['source_class'], 'repository': s['repository'], 'commit': s['commit'], 'path': s['path'], 'locator': s['locator'], 'blob_sha': s['expected_blob_sha'], 'content_sha256': content_sha256(rev.source_bytes), 'literal_value': value, 'subject': s['subject'], 'predicate': s['predicate'], 'status': s['status'], 'validity': s['validity'], 'relations': s['relations']})
    if {x['source_class'] for x in frozen} != SOURCE_CLASSES:
        raise HistoricalImportError('first materialization requires both initial source classes')
    return frozen

def _frozen(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {'record_key', 'source_class', 'repository', 'commit', 'path', 'locator', 'blob_sha', 'content_sha256', 'literal_value', 'subject', 'predicate', 'status', 'validity', 'relations'}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise HistoricalImportError('frozen record is missing exact provenance')
    s = _selector({'record_key': raw['record_key'], 'source_class': raw['source_class'], 'repository': raw['repository'], 'commit': raw['commit'], 'path': raw['path'], 'locator': raw['locator'], 'expected_blob_sha': raw['blob_sha'], 'expected_text': raw['literal_value'], 'subject': raw['subject'], 'predicate': raw['predicate'], 'status': raw['status'], 'validity': raw['validity'], 'relations': raw['relations']})
    return {**s, 'blob_sha': s.pop('expected_blob_sha'), 'content_sha256': _sha(raw['content_sha256'], 64, 'content_sha256'), 'literal_value': s.pop('expected_text')}

def import_frozen_records(records: Iterable[Mapping[str, Any]], resolver: Resolver) -> list[dict[str, Any]]:
    frozen = _dedupe(records, _frozen, 'record_key')
    by_key = {x['record_key']: x for x in frozen}
    for item in frozen:
        for name in RELATIONS:
            for target in item['relations'][name]:
                if target not in by_key:
                    raise HistoricalImportError('dangling relation record key')
    claims: dict[str, dict[str, Any]] = {}
    revisions: dict[str, ResolvedRevision] = {}
    for item in frozen:
        rev = _resolve(item, resolver, 'blob_sha')
        if content_sha256(rev.source_bytes) != item['content_sha256']:
            raise HistoricalImportError('content SHA-256 mismatch')
        if _literal(rev.source_bytes, item['locator']) != item['literal_value']:
            raise HistoricalImportError('frozen locator changed')
        claim = {'schema': 'hwm-historical-claim/v1', 'claim_id': '', 'authority': 'historical', 'subject': item['subject'], 'predicate': item['predicate'], 'value': item['literal_value'], 'provenance': {'source_class': item['source_class'], 'repository': item['repository'], 'commit': item['commit'], 'path': item['path'], 'locator': item['locator'], 'blob_sha': item['blob_sha'], 'content_sha256': item['content_sha256']}, 'validity': item['validity'], 'status': item['status'], 'relations': {k: [] for k in RELATIONS}}
        claim['claim_id'] = compute_claim_id(claim)
        claims[item['record_key']], revisions[item['record_key']] = (claim, rev)
    for key, item in by_key.items():
        claims[key]['relations'] = {name: sorted({claims[t]['claim_id'] for t in item['relations'][name]}) for name in RELATIONS}
    for key, claim in claims.items():
        rev = revisions[key]
        try:
            verify_source_binding(claim, repository=rev.repository, commit=rev.commit, path=rev.path, source_bytes=rev.source_bytes, revision_candidates=rev.revision_candidates, resolved_symbols=rev.resolved_symbols)
        except HistoricalClaimContractError as exc:
            raise HistoricalImportError(str(exc)) from exc
    try:
        rendered = materialize_ledger(claims.values())
    except HistoricalClaimContractError as exc:
        raise HistoricalImportError(str(exc)) from exc
    return [json.loads(line) for line in rendered[CLAIMS_PATH].decode().splitlines()]

def generate_ledger(selectors: Iterable[Mapping[str, Any]], resolver: Resolver) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bytes]]:
    frozen = freeze_records(selectors, resolver)
    claims = import_frozen_records(frozen, resolver)
    try:
        outputs = materialize_ledger(claims)
    except HistoricalClaimContractError as exc:
        raise HistoricalImportError(str(exc)) from exc
    return (frozen, claims, outputs)

def github_raw_resolver(repository: str, commit: str, path: str) -> Sequence[ResolvedRevision]:
    _sha(commit, 40, 'commit')
    _path(path)
    owner, name = repository.split('/', 1)
    url = f"https://raw.githubusercontent.com/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(name, safe='')}/{commit}/{urllib.parse.quote(path, safe='/')}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'hwm-control-I08-importer/1'}), timeout=30) as response:
            data = response.read(MAX_SOURCE_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise HistoricalImportError('exact Git source could not be resolved') from exc
    if len(data) > MAX_SOURCE_BYTES:
        raise HistoricalImportError('source blob exceeds bound')
    return [ResolvedRevision(repository, commit, path, data)]

def build_publication_request(*, request_id: str, expected_base: str, publication_branch: str, output_blob_shas: Mapping[str, str], existing_blob_shas: Mapping[str, str] | None=None) -> dict[str, Any] | None:
    expected_paths = {CLAIMS_PATH, CONFLICTS_PATH}
    if set(output_blob_shas) != expected_paths:
        raise HistoricalImportError('publication requires exactly two canonical paths')
    existing = dict(existing_blob_shas or {})
    if set(existing) - expected_paths:
        raise HistoricalImportError('unauthorized hwm-context path state')
    if set(existing) == expected_paths and all((existing[p] == output_blob_shas[p] for p in expected_paths)):
        return None
    changes = []
    for path in sorted(expected_paths):
        _sha(output_blob_shas[path], 40, 'output blob')
        if path in existing:
            _sha(existing[path], 40, 'existing blob')
            changes.append({'op': 'replace', 'path': path, 'blob_sha': output_blob_shas[path], 'mode': '100644', 'expected_blob_sha': existing[path]})
        else:
            changes.append({'op': 'add', 'path': path, 'blob_sha': output_blob_shas[path], 'mode': '100644'})
    request = {'schema': 'hwm-historical-ledger-publish-request/v1', 'request_id': request_id, 'repository': 'Dsamofalov/hwm-context', 'transport_issue': 2, 'expected_base': expected_base, 'publication_branch': publication_branch, 'changes': changes, 'ci': {'workflow': 'repository-bootstrap-ci.yml', 'required_check': 'bootstrap'}}
    try:
        return validate_publish_request(request)
    except Exception as exc:
        raise HistoricalImportError(str(exc)) from exc

def default_corpus_evidence() -> dict[str, Any]:
    a = generate_ledger(DEFAULT_SOURCE_SELECTORS, github_raw_resolver)
    b = generate_ledger(reversed(DEFAULT_SOURCE_SELECTORS), github_raw_resolver)
    if a != b:
        raise HistoricalImportError('repeated/reordered import is not byte-identical')
    frozen, claims, outputs = a
    return {'frozen_records': frozen, 'claims': claims, 'outputs': {p: {'git_blob_sha': git_blob_sha(d), 'content_sha256': hashlib.sha256(d).hexdigest(), 'base64': base64.b64encode(d).decode('ascii')} for p, d in sorted(outputs.items())}}

def main(argv: Sequence[str]) -> int:
    if list(argv[1:]) != ['--emit-default-evidence']:
        return 2
    evidence = default_corpus_evidence()
    print('I08_FROZEN_CORPUS=' + canonical_json(evidence['frozen_records']))
    for path in (CLAIMS_PATH, CONFLICTS_PATH):
        prefix = 'I08_CLAIMS' if path == CLAIMS_PATH else 'I08_CONFLICTS'
        item = evidence['outputs'][path]
        print(prefix + '_GIT_BLOB_SHA=' + item['git_blob_sha'])
        print(prefix + '_SHA256=' + item['content_sha256'])
        print(prefix + '_BASE64=' + item['base64'])
    return 0
if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
