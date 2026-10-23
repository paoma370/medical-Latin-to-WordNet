#!/usr/bin/env python3
"""Offline analysis of saved Latin WordNet API responses. Python 3.9+, no dependencies."""
import argparse
import collections
import csv
import hashlib
import json
import platform
import statistics
from pathlib import Path


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def analyse(results_path, words_path, out, export_review_csv=True):
    records = json.loads(results_path.read_text(encoding='utf-8'))
    with words_path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        required = {'Word', 'Medical sense', 'Non specialised sense'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Input list must be tab-separated with columns: ' + ', '.join(sorted(required)))
        words = list(reader)
    if not isinstance(records, list) or not records:
        raise ValueError('Query results must be a non-empty JSON list.')
    def input_identity(value):
        return {x.strip().casefold().replace('v', 'u') for x in value.split('/')}
    if [input_identity(x['Word']) for x in words] != [input_identity(x['lemma']) for x in records]:
        raise ValueError('Input and JSON entries differ in identity, order or multiplicity.')
    links, entries, queries, groups = [], [], [], []
    warnings = []
    for number, (record, word) in enumerate(zip(records, words), 1):
        group = word['Word']
        for csv_field, json_field in [('Medical sense', 'medical_sense'), ('Non specialised sense', 'non_medical_sense')]:
            value = record.get(json_field)
            if value is None or (isinstance(value, float) and str(value) == 'nan'):
                value = ''
            if str(value).strip() != word[csv_field].strip():
                raise ValueError(f'Sense description mismatch: {group}, {csv_field}')
        variants = [v.strip() for v in group.split('/')]
        payloads, errors = record['wordnet_synsets'], record.get('errors', {})
        unexpected = (set(payloads) | set(errors)) - set(variants)
        if unexpected:
            raise ValueError(f'Unexpected variant keys for {group}: {unexpected}')
        entry_start, link_start = len(entries), len(links)
        for variant in variants:
            payload = payloads.get(variant)
            query = dict(entry_number=number, source_entry=group, query=variant,
                         error=errors.get(variant), stored_response=payload is not None)
            if payload is None:
                if variant not in errors:
                    warnings.append(f'{variant}: spelling added to input; not queried in the saved Exeter snapshot.')
                query['query_status'] = 'request_error' if variant in errors else 'not_in_saved_snapshot'
                query.update(returned_records=0, next_page=None)
                queries.append(query)
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                raise ValueError(f'Unexpected response schema for {variant}')
            query.update(returned_records=len(payload['results']), reported_count=payload.get('count'),
                         next_page=payload.get('next'), previous_page=payload.get('previous'))
            queries.append(query)
            if payload.get('next'):
                warnings.append(f'{variant}: additional page indicated; counts cover stored records only.')
            if payload.get('count') != len(payload['results']):
                warnings.append(f'{variant}: reported count differs from stored record count.')
            for position, entry in enumerate(payload['results'], 1):
                base = dict(entry_number=number, source_entry=group, query=variant,
                            response_record_number=position, returned_lemma=entry.get('lemma'),
                            lexical_entry_uri=entry.get('uri'), lexical_pos=entry.get('pos'))
                entries.append(base)
                if entry.get('lemma') != variant:
                    warnings.append(f'{variant}: returned lemma differs: {entry.get("lemma")}')
                for category, synsets in entry['synsets'].items():
                    if not isinstance(synsets, list):
                        raise ValueError(f'Unexpected category data: {variant}/{category}')
                    for synset in synsets:
                        for key in ['offset', 'pos', 'gloss']:
                            if key not in synset:
                                raise ValueError(f'Missing synset {key}: {variant}')
                        links.append(dict(base, category=category, offset=synset['offset'],
                                          synset_pos=synset['pos'], gloss=synset['gloss'],
                                          language=synset.get('language', {}).get('abbrev'),
                                          semantic_fields=synset.get('semfield', [])))
        current_entries, current_links = entries[entry_start:], links[link_start:]
        status = ('synsets_returned' if current_links else 'records_without_synsets' if current_entries
                  else 'no_records_returned')
        groups.append(dict(entry_number=number, source_entry=group, medical_sense=word['Medical sense'],
                           non_medical_sense=word['Non specialised sense'], query_forms=variants,
                           returned_records=len(current_entries), synset_link_occurrences=len(current_links),
                           distinct_offset_pos_pairs=len({(s['offset'], s['synset_pos']) for s in current_links}),
                           status=status, errors=errors))
    n = len(groups)
    statuses = collections.Counter(g['status'] for g in groups)
    ranked = sorted(groups, key=lambda g: (-g['synset_link_occurrences'], g['entry_number']))
    categories = collections.Counter(s['category'] for s in links)
    nonempty = [g['synset_link_occurrences'] for g in groups if g['synset_link_occurrences']]
    summary = dict(
        source_entries=n, query_forms=len(queries), stored_responses=sum(q['stored_response'] for q in queries),
        logged_query_errors=sum(len(r.get('errors', {})) for r in records),
        responses_with_next_page=sum(bool(q.get('next_page')) for q in queries),
        entries_with_records=sum(bool(g['returned_records']) for g in groups),
        entries_with_synsets=statuses['synsets_returned'],
        entries_with_records_without_synsets=statuses['records_without_synsets'],
        entries_without_records=statuses['no_records_returned'],
        lexical_record_occurrences=len(entries),
        distinct_lexical_entry_uris=len({e['lexical_entry_uri'] for e in entries if e['lexical_entry_uri'] is not None}),
        synset_link_occurrences=len(links),
        distinct_offset_pos_pairs=len({(s['offset'], s['synset_pos']) for s in links}),
        distinct_language_offset_pos_triples=len({(s['language'], s['offset'], s['synset_pos']) for s in links}),
        within_entry_distinct_offset_pos_associations=sum(g['distinct_offset_pos_pairs'] for g in groups),
        category_counts=dict(categories),
        language_counts=dict(collections.Counter(s['language'] for s in links)),
        blank_gloss_occurrences=sum(not s['gloss'].strip() for s in links),
        median_links_among_entries_with_links=statistics.median(nonempty) if nonempty else None,
        entries_without_records_list=[g['source_entry'] for g in groups if not g['returned_records']],
        entries_with_records_without_synsets_list=[g['source_entry'] for g in groups if g['status']=='records_without_synsets'],
        nonliteral_links_by_entry=dict(collections.Counter(s['source_entry'] for s in links if s['category'] in {'metonymic','metaphoric'})),
        top_entries=[dict(lemma=g['source_entry'], occurrences=g['synset_link_occurrences']) for g in ranked[:10]],
        top_three_occurrences=sum(g['synset_link_occurrences'] for g in ranked[:3]),
        top_three_percent=round(100*sum(g['synset_link_occurrences'] for g in ranked[:3])/len(links), 1) if links else None,
        warnings=warnings)
    for field in ['entries_with_records','entries_with_synsets','entries_with_records_without_synsets','entries_without_records']:
        summary[field+'_percent'] = round(100*summary[field]/n, 1)
    out.mkdir(parents=True, exist_ok=True)
    dump(out/'summary.json', summary)
    dump(out/'entry_summary.json', groups)
    dump(out/'query_audit.json', queries)
    dump(out/'synset_links.json', links)
    # One blank assessment per source entry and unique language/offset/POS candidate.
    seen, review = set(), []
    for link in links:
        key = (link['entry_number'], link['language'], link['offset'], link['synset_pos'])
        if key not in seen:
            seen.add(key)
            source = groups[link['entry_number'] - 1]
            review.append(dict(link,
                               review_id=':'.join(str(part) for part in key),
                               medical_sense=source['medical_sense'],
                               non_medical_sense=source['non_medical_sense'],
                               assessment=None, evidence_reference=None, notes=None))
    if export_review_csv:
        dump(out/'manual_review.json', review)
    # Match the JSON's deduplication exactly: one candidate per source entry,
    # language, offset and POS. Quote commas, embedded quotes and line breaks.
    fields = ['review_id', 'entry_number', 'source_entry', 'medical_sense',
              'non_medical_sense', 'query', 'returned_lemma', 'lexical_entry_uri',
              'lexical_pos', 'response_record_number', 'category', 'offset',
              'synset_pos', 'language', 'gloss', 'semantic_fields',
              'assessment', 'evidence_reference', 'notes']
    review_csv = out/'manual_review.csv'
    if not export_review_csv:
        pass
    elif review_csv.exists():
        # Never replace a potentially annotated CSV during a repeated analysis.
        print(f'Keeping existing {review_csv}; use a new --out directory to regenerate the template.')
    else:
        with review_csv.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for candidate in review:
                row = dict(candidate)
                row['semantic_fields'] = json.dumps(row['semantic_fields'], ensure_ascii=False)
                writer.writerow(row)
    dump(out/'provenance.json', dict(python=platform.python_version(),
        inputs=[dict(file=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in [results_path, words_path]],
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        interpretation='Offline analysis of supplied responses; execution time is not the original API query date.'))
    lines = ['# Retrieval summary', '', '| Measure | Value |','|---|---:|']
    for key in ['source_entries','query_forms','entries_with_records','entries_with_synsets',
                'entries_with_records_without_synsets','entries_without_records','synset_link_occurrences',
                'distinct_offset_pos_pairs','logged_query_errors','responses_with_next_page']:
        lines.append(f'| {key.replace("_", " ")} | {summary[key]} |')
    lines += ['', '## Returned candidates by source entry', '', '| Entry | Records | Link occurrences | Distinct offset–POS pairs | Status |', '|---|---:|---:|---:|---|']
    for g in groups:
        lines.append(f'| {g["source_entry"]} | {g["returned_records"]} | {g["synset_link_occurrences"]} | {g["distinct_offset_pos_pairs"]} | {g["status"]} |')
    lines += ['', 'These are retrieval counts, not validated medical-sense coverage or measurements of historical change.',
              'A no-record outcome with a query error must not be interpreted as an empty successful lookup.',
              'Concept identity is counted using offset plus POS within this saved resource. Offsets are not asserted to be portable across WordNet releases.',
              'The API payload does not supply complete synset-member lists; synonyms cannot be reconstructed from this file alone.']
    (out/'summary.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


REFERENCE = dict(source_entries=69, query_forms=74, logged_query_errors=0, responses_with_next_page=0,
                 entries_with_records=63, entries_with_synsets=56, entries_with_records_without_synsets=7,
                 entries_without_records=6, synset_link_occurrences=675, distinct_offset_pos_pairs=643,
                 top_three_occurrences=288)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--words', required=True, type=Path)
    parser.add_argument('--out', type=Path, default=Path('analysis'))
    parser.add_argument('--lila', type=Path, help='Optional local LiLa revision Turtle file')
    parser.add_argument('--check-reference', action='store_true', help='Check the numerical claims for the supplied 2026-10-20 files')
    args = parser.parse_args()
    summary = analyse(args.results, args.words, args.out, export_review_csv=not bool(args.lila))
    if args.check_reference:
        for key, expected in REFERENCE.items():
            actual = summary['stored_responses'] if key == 'query_forms' else summary[key]
            if actual != expected:
                raise SystemExit(f'Reference mismatch for {key}: {summary[key]} != {expected}')
        if summary['category_counts'] != {'literal':652,'metonymic':6,'metaphoric':17}:
            raise SystemExit('Reference category counts differ.')
        print('All reference numerical claims reproduced.')
    print(json.dumps({k: summary[k] for k in REFERENCE}, indent=2))

    if args.lila:
        from verify_lila import verify
        verify(args.lila, args.words, args.out, args.out)
