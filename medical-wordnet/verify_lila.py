"""Verify lexical mappings against a local LiLa revision; no cross-version offset joins."""
import csv
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def normalise(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.strip().casefold())
                   if not unicodedata.combining(c)).replace('v', 'u')


def verify(ttl_path, words_path, exeter_directory, out):
    import rdflib
    from rdflib import Graph, Namespace, RDF, RDFS, SKOS
    O = Namespace('http://www.w3.org/ns/lemon/ontolex#')
    VS = Namespace('http://www.w3.org/2003/06/sw-vocab-status/ns#')
    graph = Graph().parse(str(ttl_path), format='turtle')
    with words_path.open(encoding='utf-8-sig', newline='') as stream:
        words = list(csv.DictReader(stream, delimiter='\t'))
    exeter = json.loads((exeter_directory/'entry_summary.json').read_text())
    indexed = defaultdict(set)
    for entry in graph.subjects(RDF.type, O.LexicalEntry):
        labels = set(str(x) for x in graph.objects(entry, RDFS.label))
        for form in graph.objects(entry, O.canonicalForm):
            labels.update(str(x) for x in graph.objects(form, O.writtenRep))
        for label in labels:
            indexed[normalise(label)].add(entry)
    rows, summaries = [], []
    for number, (word, baseline) in enumerate(zip(words, exeter), 1):
        if word['Word'] != baseline['source_entry']:
            raise ValueError('LiLa input and Exeter summary are not aligned.')
        variants = [x.strip() for x in word['Word'].split('/')]
        group_entries, group_concepts, reviewed = set(), set(), set()
        matched_entries = defaultdict(set)
        for variant in variants:
            for entry in indexed.get(normalise(variant), []):
                matched_entries[entry].add(variant)
        for entry in sorted(matched_entries, key=str):
                matched_queries = sorted(matched_entries[entry])
                variant = matched_queries[0]
                group_entries.add(str(entry))
                labels = sorted(str(x) for x in graph.objects(entry,RDFS.label))
                concepts = set(graph.objects(entry,O.evokes))
                sense_map = defaultdict(set)
                senses = set(graph.objects(entry,O.sense)) | set(graph.subjects(O.isSenseOf,entry))
                for sense in senses:
                    for concept in graph.objects(sense,O.isLexicalizedSenseOf):
                        concepts.add(concept); sense_map[concept].add(sense)
                for concept in sorted(concepts,key=str):
                    group_concepts.add(str(concept))
                    statuses = sorted({str(x) for sense in sense_map[concept] for x in graph.objects(sense,VS.term_status)})
                    if 'reviewed' in statuses:reviewed.add(str(concept))
                    linked_entries = set(graph.subjects(O.evokes,concept)) | set(graph.objects(concept,O.isEvokedBy))
                    member_labels = sorted({str(label) for member in linked_entries for label in graph.objects(member,RDFS.label)})
                    rows.append(dict(entry_number=number, source_entry=word['Word'],query=variant,matched_query_forms=matched_queries,
                        medical_sense=word['Medical sense'],non_medical_sense=word['Non specialised sense'],
                        lila_entry_uri=str(entry),lila_entry_labels=labels,
                        match_type='exact_label' if any(v in labels for v in matched_queries) else 'normalised_label_or_canonical_form',
                        lila_concept_uri=str(concept),definitions=sorted(str(x) for x in graph.objects(concept,SKOS.definition)),
                        external_links=sorted(str(x) for x in graph.objects(concept,RDFS.seeAlso)),
                        lila_sense_uris=sorted(str(x) for x in sense_map[concept]),term_status=statuses,
                        resource_synset_member_labels=member_labels,
                        medical_assessment=None,evidence_reference=None,notes=None))
        summaries.append(dict(entry_number=number,source_entry=word['Word'],
            exeter_records=baseline['returned_records'],exeter_links=baseline['synset_link_occurrences'],
            lila_lexical_entries=len(group_entries),lila_distinct_concepts=len(group_concepts),
            lila_reviewed_concepts=len(reviewed),
            verification_status='present_in_attached_revision' if group_entries else 'not_found_in_attached_revision',
            exeter_only_in_available_sources=bool(baseline['returned_records']) and not group_entries))
    def save(name,value):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    out.mkdir(exist_ok=True,parents=True)
    save('lila_candidates.json',rows);save('lila_entry_summary.json',summaries)
    def csv_export(name,data):
        path=out/name
        if path.exists():
            print(f'Keeping existing {path}; use a new --out directory to regenerate.');return
        with path.open('x',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0]) if data else ['source_entry'])
            writer.writeheader()
            for row in data:
                writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    # Evaluation CSVs are exported only after applying LiLa-first selection.
    from select_evaluation import export_selected
    export_selected(out)
    matched=[x for x in summaries if x['lila_lexical_entries']]
    absent=[x for x in summaries if not x['lila_lexical_entries']]
    both=[x for x in matched if x['exeter_records']]
    stats=dict(source_entries=len(words),rdf_triples=len(graph),
        entries_present_in_revision=len(matched),entries_absent_from_revision=len(absent),
        entries_present_percent=round(100*len(matched)/len(words),1),
        entries_with_lila_concepts=sum(bool(x['lila_distinct_concepts']) for x in summaries),
        lila_candidate_occurrences=len(rows),
        lila_distinct_concepts=len({r['lila_concept_uri'] for r in rows}),
        lila_entry_concept_pairs=len({(r['lila_entry_uri'],r['lila_concept_uri']) for r in rows}),
        term_status_counts=dict(Counter(s for r in rows for s in r['term_status'])),
        present_in_both=len(both),lila_only=len(matched)-len(both),
        exeter_only=sum(x['exeter_only_in_available_sources'] for x in summaries),
        neither=sum(not x['exeter_records'] for x in absent),
        absent_entries=[x['source_entry'] for x in absent],
        lila_only_entries=[x['source_entry'] for x in matched if not x['exeter_records']],
        entries_with_blank_definitions=sorted({r['source_entry'] for r in rows if not r['definitions']}),
        snapshot_sha256=hashlib.sha256(ttl_path.read_bytes()).hexdigest(),rdflib_version=rdflib.__version__,
        matching_normalisation='casefold, diacritic removal, v mapped to u; no lemmatisation or i/j expansion',
        resource_descriptions=sorted(str(x) for x in graph.objects(None,Namespace('http://purl.org/dc/terms/').description)),
        notes=['Counts are resource-specific lexical coverage, not medical-sense validation.',
               'No numeric-offset equality or automatic replacement between Exeter and LiLa is used.',
               'Absence means not found by the documented label matching in this selected revision.'])
    save('lila_summary.json',stats)
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    return stats
