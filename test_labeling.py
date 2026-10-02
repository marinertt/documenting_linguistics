import unittest
import pandas as pd
from labeling import propose_labels

class LabelTests(unittest.TestCase):
    def frame(self, pairs):
        return pd.DataFrame([dict(annotation_id=f'a{i}',timestamp='00:00:01',transcript=s,translation=t) for i,(s,t) in enumerate(pairs)])
    def test_intersection_and_elimination(self):
        df=self.frame([('foo bar x','história boa'),('foo bar y','história boa longa')])
        result=next(p for p in propose_labels(df,[])['suggestions'] if p['word']=='foo')
        self.assertEqual(result['shared'],['boa','historia'])
        result=next(p for p in propose_labels(df,[{'word':'bar','meaning':'boa'}])['suggestions'] if p['word']=='foo')
        self.assertEqual(result['shared'],['historia'])
        self.assertEqual(result['status'],'single-candidate')
    def test_sparse_translation_keeps_source_word(self):
        r=propose_labels(self.frame([('pare','mandou abrir'),('pare',''),('pare','')]),[])['suggestions'][0]
        self.assertEqual(r['word'],'pare')
        self.assertEqual(r['support'],3)
        self.assertEqual(r['translated_support'],1)
        self.assertEqual(r['status'],'insufficient')
        self.assertEqual({c['word'] for c in r['candidates']},{'mandou','abrir'})
    def test_no_overlap(self):
        r=propose_labels(self.frame([('foo','estória'),('foo','cachoeira')]),[])['suggestions'][0]
        self.assertEqual(r['status'],'unresolved')
    def test_singletons_not_proposed(self):
        self.assertEqual(propose_labels(self.frame([('foo','bar')]),[])['suggestions'],[])
