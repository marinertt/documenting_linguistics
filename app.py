"""Run with: venv/bin/python app.py"""
import json
import mimetypes
import re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from linguisticdocs.eaf_dataframe import eaf_dataframe
from linguisticdocs.corpus_search import search_translation, search_transcript
from lexicon import Lexicon
from labeling import propose_labels, tokens
from volumes import Volumes
from folder_picker import choose_folder
from records import record_index, load_record

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'data/eaf_example.eaf'
CORPUS = eaf_dataframe(SOURCE)
BANK = Lexicon(ROOT / 'data/lexicon.json')
VOLUMES = Volumes(ROOT / 'data/volumes.json')

class Handler(BaseHTTPRequestHandler):
    def send(self, body, status=200, content_type='application/json; charset=utf-8'):
        body = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def context(self, values):
        if values.get('volume_id'):
            return load_record(VOLUMES, values['volume_id'], values.get('record_id'),
                               values.get('eaf'), values.get('tier'), values.get('translation'))
        return CORPUS, str(SOURCE), {}

    def serve_audio(self, args):
        started=False
        try:
            with VOLUMES.audio_stream(args.get('volume_id'),args.get('path')) as (size,chunks):
                start,end=0,size-1
                header=self.headers.get('Range')
                if header:
                    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
                    if not match or not any(match.groups()):raise ValueError('Invalid range')
                    left,right=match.groups()
                    if left:
                        start=int(left);end=min(int(right),size-1) if right else size-1
                    else:start=max(0,size-int(right))
                    if start>end or start>=size:raise ValueError('Invalid range')
                self.send_response(206 if header else 200)
                self.send_header('Content-Type',mimetypes.guess_type(args['path'])[0] or 'audio/wav')
                self.send_header('Accept-Ranges','bytes')
                self.send_header('Content-Length',str(max(0,end-start+1)))
                if header:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.end_headers();started=True
                if size:
                    for chunk in chunks(start,end):self.wfile.write(chunk)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            if not started:self.send('{"error":"Audio unavailable or range invalid"}',416)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ('/', '/style.css', '/app.js'):
            name = {'/':'index.html', '/style.css':'style.css', '/app.js':'app.js'}[url.path]
            mime = {'index.html':'text/html', 'style.css':'text/css', 'app.js':'text/javascript'}[name]
            return self.send((ROOT/'web'/name).read_bytes(), content_type=mime+'; charset=utf-8')
        if url.path == '/api/records':
            return self.send(json.dumps(record_index(VOLUMES),ensure_ascii=False))
        if url.path == '/api/record-audio':
            return self.serve_audio({k:v[0] for k,v in parse_qs(url.query).items()})
        if url.path == '/api/corpus':
            args = parse_qs(url.query)
            query = args.get('q', [''])[0].strip()
            mode = args.get('mode', ['transcript'])[0]
            try:
                corpus,source,record=self.context({k:v[0] for k,v in args.items()})
            except Exception as e:
                return self.send(json.dumps({'error':str(e)}),400)
            found = corpus
            if query:
                search = search_translation if mode == 'translation' else search_transcript
                found = search(corpus, query, whole_word=args.get('partial', ['false'])[0] != 'true')
            columns = ['annotation_id','timestamp','end_timestamp','start_ms','end_ms','transcript','translation','participant','morphemes','glosses','associated_annotations']
            return self.send(json.dumps({'rows':json.loads(found[columns].to_json(orient='records', force_ascii=False)), 'total':len(corpus), 'translated':int((corpus.translation!='').sum()), 'source':source, 'record':record}, ensure_ascii=False))
        if url.path == '/api/volumes':
            return self.send(json.dumps(VOLUMES.list(), ensure_ascii=False))
        if url.path == '/api/labels':
            corpus,_,_=self.context({k:v[0] for k,v in parse_qs(url.query).items()})
            return self.send(json.dumps(propose_labels(corpus, list(BANK._load()['entries'].values())), ensure_ascii=False))
        if url.path == '/api/lexicon':
            return self.send(json.dumps(list(BANK._load()['entries'].values()), ensure_ascii=False))
        self.send('{"error":"Not found"}', 404)

    def do_POST(self):
        if self.path not in ('/api/lexicon', '/api/labels/confirm', '/api/volumes/mount', '/api/volumes/browse', '/api/volumes/unmount', '/api/volumes/choose-folder', '/api/volumes/open'):
            return self.send('{"error":"Not found"}', 404)
        # Only accept same-origin JSON writes from the local UI.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.send('{"error":"Origin not allowed"}', 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 32000 or self.headers.get_content_type() != 'application/json':
                raise ValueError('Expected a small JSON request')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
            if self.path.startswith('/api/volumes/'):
                action = self.path.rsplit('/',1)[1]
                if action == 'choose-folder':
                    result = choose_folder()
                elif action == 'mount':
                    result = VOLUMES.mount(body)
                elif action == 'open':
                    result = VOLUMES.open_document(body.get('id'), body.get('path'))
                elif action == 'browse':
                    result = VOLUMES.browse(body.get('id'), body.get('folder',''), body.get('cursor'))
                else:
                    result = VOLUMES.unmount(body.get('id'))
                return self.send(json.dumps(result, ensure_ascii=False))
            for field in ['word','meaning','notes','part_of_speech']:
                if not isinstance(body.get(field, ''), str):
                    raise ValueError('Fields must be text')
            corpus, source, _ = self.context(body.get('context',{}))
            if self.path == '/api/labels/confirm':
                target = body.get('meaning', '')
                word = body.get('word', '')
                proposals = propose_labels(corpus, list(BANK._load()['entries'].values()))
                proposal = next((p for p in proposals['suggestions'] if p['word'] == word), None)
                if proposal is None or target not in [c['word'] for c in proposal['candidates']]:
                    raise ValueError('This candidate is no longer available. Refresh the workspace.')
                try:
                    existing = BANK.get(word)
                except KeyError:
                    existing = {}
                if existing.get('meaning') and tokens(existing['meaning'], True) != [target]:
                    raise ValueError('This word already has a different meaning. Review it in My lexicon first.')
                body = {'word':word, 'meaning':target}
            entry = BANK.add(body.get('word',''), corpus, source_file=source,
                **{k:body[k] for k in ['meaning','notes','part_of_speech'] if k in body})
            self.send(json.dumps(entry, ensure_ascii=False))
        except (ValueError, KeyError) as error:
            self.send(json.dumps({'error':str(error)}), 400)
        except Exception:
            self.send('{"error":"Could not save the entry. Please try again."}', 500)

if __name__ == '__main__':
    print('Corpus Studio: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
