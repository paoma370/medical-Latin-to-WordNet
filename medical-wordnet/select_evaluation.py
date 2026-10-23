"""LiLa-first source selection. CSV outputs have disjoint source-entry sets."""
import csv
import json
from pathlib import Path


def export_selected(out):
    out=Path(out)
    def load(name):return json.loads((out/name).read_text(encoding='utf-8'))
    source=load('entry_summary.json');coverage=load('lila_entry_summary.json')
    lila=load('lila_candidates.json');exeter=load('synset_links.json')
    selected_lila={r['source_entry'] for r in coverage if r['lila_lexical_entries']}
    selected_exeter={r['source_entry'] for r in coverage if r['exeter_only_in_available_sources']}
    assert selected_lila.isdisjoint(selected_exeter)
    targets={r['source_entry']:r for r in source}
    fields=['review_id','resource','source_entry','query','medical_sense','non_medical_sense',
            'retrieval_status','lexical_entry_id','returned_lemma','sense_ids','concept_id',
            'definitions','category','source_review_status','assessment','evidence_reference','notes']
    lila_rows=[]
    for r in lila:
        assert r['source_entry'] in selected_lila
        lila_rows.append(dict(review_id='lila|'+str(r['entry_number'])+'|'+r['lila_entry_uri']+'|'+r['lila_concept_uri'],
            resource='LiLa revision',source_entry=r['source_entry'],query=r.get('matched_query_forms',r['query']),
            medical_sense=r['medical_sense'],non_medical_sense=r['non_medical_sense'],
            retrieval_status='candidate',lexical_entry_id=r['lila_entry_uri'],returned_lemma=r['lila_entry_labels'],
            sense_ids=r['lila_sense_uris'],concept_id=r['lila_concept_uri'],definitions=r['definitions'],
            category='',source_review_status=r['term_status'],assessment='',evidence_reference='',notes=''))
    fallback_rows=[];seen=set()
    for r in exeter:
        if r['source_entry'] not in selected_exeter:continue
        key=(r['source_entry'],r['language'],r['offset'],r['synset_pos'])
        if key in seen:continue
        seen.add(key);target=targets[r['source_entry']]
        fallback_rows.append(dict(review_id='exeter|'+'|'.join(str(x) for x in key),resource='Exeter API',
            source_entry=r['source_entry'],query=r['query'],medical_sense=target['medical_sense'],
            non_medical_sense=target['non_medical_sense'],retrieval_status='candidate',
            lexical_entry_id=r['lexical_entry_uri'],returned_lemma=r['returned_lemma'],sense_ids='',
            concept_id=r['offset']+'-'+r['synset_pos'],definitions=r['gloss'],category=r['category'],
            source_review_status='',assessment='',evidence_reference='',notes=''))
    with_links={r['source_entry'] for r in fallback_rows}
    for target in source:
        if target['source_entry'] in selected_exeter and target['source_entry'] not in with_links:
            fallback_rows.append(dict(review_id='exeter|'+str(target['entry_number'])+'|no_synsets',
                resource='Exeter API',source_entry=target['source_entry'],query=target['query_forms'],
                medical_sense=target['medical_sense'],non_medical_sense=target['non_medical_sense'],
                retrieval_status='lexical_records_without_synsets',assessment='',evidence_reference='',notes=''))
    for filename,rows in [('lila_evaluation.csv',lila_rows),('exeter_only_evaluation.csv',fallback_rows)]:
        path=out/filename
        if path.exists():print(f'Keeping existing {path}; use a fresh --out directory to regenerate.')
        else:
            with path.open('x',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                for row in rows:
                    writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    summary=dict(selection_rule='LiLa for an entire source entry when represented there; Exeter only when absent from LiLa and Exeter returns lexical records.',
        lila_entries=len(selected_lila),lila_evaluation_rows=len(lila_rows),
        exeter_only_entries=len(selected_exeter),exeter_candidate_rows=len(seen),
        exeter_entries_without_links=sorted(selected_exeter-with_links),exeter_evaluation_rows=len(fallback_rows),
        entries_with_selected_synsets=len(selected_lila)+len(with_links),
        unmatched_entries=[r['source_entry'] for r in source if r['source_entry'] not in selected_lila|selected_exeter],
        lila_entry_list=sorted(selected_lila),exeter_only_entry_list=sorted(selected_exeter))
    (out/'selected_source_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    print(json.dumps(export_selected(parser.parse_args().out),indent=2))
