"""API checks using an isolated lexicon and in-memory HTTP requests."""
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
import app
from lexicon import Lexicon

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = app.BANK
        app.BANK = Lexicon(Path(self.temp.name)/'lexicon.json')
    def tearDown(self):
        app.BANK = self.previous
        self.temp.cleanup()
    def request(self, path, body=None):
        handler = app.Handler.__new__(app.Handler)
        handler.path = path
        handler.headers = Message()
        payload = json.dumps(body).encode() if body is not None else b''
        handler.headers['Content-Type']='application/json'
        handler.headers['Content-Length']=str(len(payload))
        handler.rfile=io.BytesIO(payload)
        captured={}
        def send(value,status=200,content_type='application/json'):
            captured.update(value=value,status=status)
        handler.send=send
        (handler.do_POST if body is not None else handler.do_GET)()
        return captured['status'],json.loads(captured['value'])
    def test_browse_and_search(self):
        status,data=self.request('/api/corpus')
        self.assertEqual(status,200)
        self.assertEqual(len(data['rows']),48)
        _,data=self.request('/api/corpus?q=estoria&mode=translation')
        self.assertEqual(data['rows'][0]['annotation_id'],'a1')
        _,data=self.request('/api/corpus?q=zzzzzz')
        self.assertEqual(data['rows'],[])
    def test_save_reload_and_deduplicate(self):
        body={'word':'ĩyẽ','meaning':'','notes':'test note'}
        status,entry=self.request('/api/lexicon',body)
        self.assertEqual(status,200)
        self.assertTrue(entry['examples'])
        self.request('/api/lexicon',body)
        _,entries=self.request('/api/lexicon')
        self.assertEqual(len(entries),1)
        self.assertEqual(len(entries[0]['examples']),len(entry['examples']))
        self.assertEqual(entries[0]['notes'],'test note')
    def test_label_confirmation(self):
        _,result=self.request('/api/labels')
        proposal=next(p for p in result['suggestions'] if 'cachoeira' in p['shared'] and p['translated_support']==4)
        word=proposal['word']
        status,entry=self.request('/api/labels/confirm',{'word':word,'meaning':'cachoeira'})
        self.assertEqual(status,200)
        self.assertEqual(entry['meaning'],'cachoeira')
        self.assertTrue(entry['examples'])
        status,_=self.request('/api/labels/confirm',{'word':'not-a-candidate','meaning':'cachoeira'})
        self.assertEqual(status,400)

    def test_invalid_word(self):
        status,_=self.request('/api/lexicon',{'word':' '})
        self.assertEqual(status,400)
        self.assertFalse(app.BANK.path.exists())

if __name__=='__main__':unittest.main()
