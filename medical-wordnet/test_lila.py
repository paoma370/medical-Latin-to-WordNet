"""Small offline regression test: lexical links only, not neighbouring concepts."""
import csv
import json
import tempfile
from pathlib import Path
from verify_lila import verify, normalise
assert normalise("calvaria") == normalise("caluaria")
assert normalise("valetudo") == normalise("ualetudo")

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    ttl=root/'test.ttl'
    ttl.write_text('''@prefix o: <http://www.w3.org/ns/lemon/ontolex#> .
@prefix r: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix s: <http://www.w3.org/2004/02/skos/core#> .
@prefix v: <http://www.w3.org/2003/06/sw-vocab-status/ns#> .
@prefix t: <http://test/> .
t:entry a o:LexicalEntry; r:label "tēstis"; o:sense t:sense; o:evokes t:concept .
t:sense o:isSenseOf t:entry; o:isLexicalizedSenseOf t:concept; v:term_status "reviewed" .
t:concept s:definition "test fixture: gland"; t:related t:neighbour .
t:neighbour a o:LexicalConcept; s:definition "not a lexical mapping" .
''')
    words=root/'words.tsv'
    with words.open('w',newline='') as f:
        writer=csv.writer(f,delimiter='\t');writer.writerow(['Word','Medical sense','Non specialised sense'])
        writer.writerows([['testis','gland','witness'],['missing','unknown','unknown']])
    (root/'entry_summary.json').write_text(json.dumps([
        dict(source_entry='testis',returned_records=1,synset_link_occurrences=1, entry_number=1, medical_sense='gland', non_medical_sense='witness', query_forms=['testis']),
        dict(source_entry='missing',returned_records=1,synset_link_occurrences=0, entry_number=2, medical_sense='unknown', non_medical_sense='unknown', query_forms=['missing'])]))
    (root/'synset_links.json').write_text('[]')
    result=verify(ttl,words,root,root)
    rows=json.loads((root/'lila_candidates.json').read_text())
    assert result['entries_present_in_revision']==1 and result['exeter_only']==1
    assert len(rows)==1 and rows[0]['lila_concept_uri']=='http://test/concept'
    assert rows[0]['match_type']=='normalised_label_or_canonical_form'
    assert rows[0]['term_status']==['reviewed']
    with (root/'lila_evaluation.csv').open(encoding='utf-8-sig',newline='') as f:
        assert len(list(csv.DictReader(f)))==1
    # Two equivalent queries must not duplicate the same lexical mapping.
    text=words.read_text().replace('testis\t', 'testis/tēstis\t')
    words.write_text(text)
    baseline=json.loads((root/'entry_summary.json').read_text())
    baseline[0]['source_entry']='testis/tēstis'
    (root/'entry_summary.json').write_text(json.dumps(baseline))
    verify(ttl,words,root,root)
    assert len(json.loads((root/'lila_candidates.json').read_text()))==1
    # Preserve user annotations on reruns.
    review=root/'lila_evaluation.csv';review.write_text('annotated copy',encoding='utf-8')
    verify(ttl,words,root,root)
    assert review.read_text()=='annotated copy'
print('PASS: normalised lookup, sense paths, no neighbour expansion, statuses, CSV and annotation preservation.')
