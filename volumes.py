"""Application-level, read-only connections to local, S3 and Azure storage."""
from contextlib import contextmanager, ExitStack
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class VolumeError(ValueError):
    pass


class Volumes:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def list(self):
        with self.lock:
            return json.loads(self.path.read_text()) if self.path.exists() else []

    def _save(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, delete=False) as f:
                name = f.name
                json.dump(rows, f, ensure_ascii=False, indent=2)
            os.replace(name, self.path)
        finally:
            if name and Path(name).exists():
                Path(name).unlink()

    def configure(self, body):
        provider = body.get('provider')
        fields = {'local':['path'], 's3':['bucket','prefix','region','profile'],
                  'azure':['account','container','prefix']}
        if provider not in fields:
            raise VolumeError('Choose Local, Amazon S3, or Azure Blob Storage.')
        row = {'provider':provider}
        for key in ['name'] + fields[provider]:
            value = body.get(key, '')
            if not isinstance(value, str) or len(value) > 2048:
                raise VolumeError(f'Invalid {key}.')
            row[key] = value.strip()
        if not row['name']:
            raise VolumeError('Give this volume a name.')
        if provider == 'local':
            if not row['path']:
                raise VolumeError('Enter a local folder path.')
            folder = Path(row['path']).expanduser().resolve()
            if not folder.is_dir():
                raise VolumeError('The local folder does not exist or is not a directory.')
            row['path'] = str(folder)
            row['location'] = str(folder)
        else:
            row['prefix'] = row['prefix'].strip('/')
            if row['prefix']:
                row['prefix'] += '/'
            if provider == 's3':
                if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', row['bucket']):
                    raise VolumeError('Enter an S3 bucket name, without s3:// or a path.')
                row['location'] = f"s3://{row['bucket']}/{row['prefix']}"
            else:
                if not re.fullmatch(r'[a-z0-9]{3,24}', row['account']):
                    raise VolumeError('Enter an Azure storage account name (3–24 lowercase letters or numbers).')
                if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', row['container']):
                    raise VolumeError('Enter an Azure container name (3–63 lowercase letters, numbers or hyphens).')
                row['location'] = f"https://{row['account']}.blob.core.windows.net/{row['container']}/{row['prefix']}"
        return row

    def mount(self, body):
        row = self.configure(body)
        preview = self._browse(row, '', None)  # Do not save failed connections.
        row.update(id=uuid.uuid4().hex, verified_at=datetime.now(timezone.utc).isoformat())
        with self.lock:
            rows = self.list()
            if any(r['provider']==row['provider'] and r['location']==row['location'] for r in rows):
                raise VolumeError('This location is already mounted.')
            rows.append(row)
            self._save(rows)
        return {'volume':row, 'listing':preview}

    def unmount(self, volume_id):
        with self.lock:
            rows = self.list()
            if not any(r['id']==volume_id for r in rows):
                raise VolumeError('Volume not found.')
            self._save([r for r in rows if r['id'] != volume_id])
        return {'ok':True}

    def browse(self, volume_id, folder='', cursor=None):
        row = next((r for r in self.list() if r['id']==volume_id), None)
        if row is None:
            raise VolumeError('Volume not found.')
        return self._browse(row, folder, cursor)

    @contextmanager
    def audio_stream(self, volume_id, path):
        """Yield size and a range-reader without loading the recording into memory."""
        row=next((r for r in self.list() if r['id']==volume_id),None)
        if row is None or not isinstance(path,str) or path.startswith('/') or '..' in PurePosixPath(path).parts or '\\' in path:
            raise VolumeError('Invalid audio location.')
        if PurePosixPath(path).suffix.lower() not in {'.wav','.mp3','.m4a','.ogg','.flac','.aac'}:
            raise VolumeError('Not a supported audio file.')
        with ExitStack() as stack:
            if row['provider']=='local':
                base=Path(row['path']).resolve()
                file=(base/path).resolve()
                if not file.is_relative_to(base) or not file.is_file():raise VolumeError('Audio is outside this volume.')
                stream=stack.enter_context(file.open('rb'))
                size=file.stat().st_size
                def chunks(start,end):
                    stream.seek(start)
                    remaining=end-start+1
                    while remaining>0:
                        chunk=stream.read(min(1024*1024,remaining))
                        if not chunk:break
                        remaining-=len(chunk)
                        yield chunk
            elif row['provider']=='s3':
                import boto3
                from botocore.config import Config
                client=stack.enter_context(boto3.Session(profile_name=row['profile'] or None,region_name=row['region'] or None).client('s3',config=Config(connect_timeout=8,read_timeout=30,retries={'max_attempts':1})))
                key=row['prefix']+path
                size=client.head_object(Bucket=row['bucket'],Key=key)['ContentLength']
                def chunks(start,end):
                    response=client.get_object(Bucket=row['bucket'],Key=key,Range=f'bytes={start}-{end}')
                    with response['Body'] as stream:
                        yield from stream.iter_chunks(chunk_size=1024*1024)
            else:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import BlobClient
                credential=stack.enter_context(DefaultAzureCredential(exclude_interactive_browser_credential=True))
                blob=stack.enter_context(BlobClient(account_url=f"https://{row['account']}.blob.core.windows.net",container_name=row['container'],blob_name=row['prefix']+path,credential=credential,connection_timeout=8,read_timeout=30,retry_total=1))
                size=blob.get_blob_properties().size
                def chunks(start,end):
                    yield from blob.download_blob(offset=start,length=end-start+1).chunks()
            yield size,chunks

    def open_document(self, volume_id, path):
        """Read a bounded document from the selected mount for browser preview."""
        import base64
        import mimetypes
        row = next((r for r in self.list() if r['id']==volume_id), None)
        if row is None:
            raise VolumeError('Volume not found.')
        if not isinstance(path,str) or not path or path.startswith('/') or '..' in PurePosixPath(path).parts or '\\' in path:
            raise VolumeError('Invalid document path.')
        limit = 10 * 1024 * 1024
        try:
            if row['provider']=='local':
                base = Path(row['path']).resolve()
                file = (base/path).resolve()
                if not file.is_relative_to(base) or not file.is_file():
                    raise VolumeError('Document is not a file inside this volume.')
                with file.open('rb') as stream:
                    data = stream.read(limit+1)
            elif row['provider']=='s3':
                import boto3
                from botocore.config import Config
                session = boto3.Session(profile_name=row['profile'] or None,region_name=row['region'] or None)
                with session.client('s3',config=Config(connect_timeout=8,read_timeout=15,retries={'max_attempts':1})) as client:
                    response = client.get_object(Bucket=row['bucket'],Key=row['prefix']+path,Range=f'bytes=0-{limit}')
                    with response['Body'] as stream:
                        data = stream.read(limit+1)
            else:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import ContainerClient
                with DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
                    with ContainerClient(account_url=f"https://{row['account']}.blob.core.windows.net",container_name=row['container'],credential=credential,connection_timeout=8,read_timeout=15,retry_total=1) as client:
                        blob = client.get_blob_client(row['prefix']+path)
                        size = blob.get_blob_properties().size
                        if size>limit:
                            raise VolumeError('Preview supports files up to 10 MB.')
                        data = blob.download_blob().readall() if size else b''
            if len(data)>limit:
                raise VolumeError('Preview supports files up to 10 MB.')
            result = {'name':PurePosixPath(path).name,'path':path,'size':len(data)}
            mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            try:
                text = data.decode('utf-8-sig')
                if '\x00' in text:
                    raise UnicodeError()
                return result | {'kind':'text','text':text,'mime':'text/plain'}
            except UnicodeError:
                return result | {'kind':'binary','data':base64.b64encode(data).decode('ascii'),'mime':mime}
        except VolumeError:
            raise
        except Exception:
            raise VolumeError('Could not open this document. Check that it exists and you have read access.') from None

    def _browse(self, row, folder, cursor):
        if not isinstance(folder, str) or folder.startswith('/') or '..' in PurePosixPath(folder).parts or '\\' in folder:
            raise VolumeError('Invalid folder path.')
        if cursor is not None and (not isinstance(cursor, str) or len(cursor)>16000):
            raise VolumeError('Invalid page token.')
        try:
            if row['provider']=='local':
                base = Path(row['path']).resolve()
                current = (base/folder).resolve()
                if not current.is_relative_to(base):
                    raise VolumeError('This folder is outside the mounted location.')
                items = []
                with os.scandir(current) as directory:
                    for entry in directory:
                        # Symlinks are omitted so browsing stays inside the mount.
                        if entry.is_symlink():
                            continue
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if not is_dir and not entry.is_file(follow_symlinks=False):
                            continue
                        items.append({'name':entry.name, 'folder':is_dir,
                                      'path':str(PurePosixPath(folder)/entry.name),
                                      'size':None if is_dir else entry.stat().st_size})
                items.sort(key=lambda r:(not r['folder'],r['name'].casefold()))
                offset = int(cursor or 0)
                if offset<0:
                    raise VolumeError('Invalid page token.')
                return {'items':items[offset:offset+100], 'next_cursor':str(offset+100) if len(items)>offset+100 else None}
            prefix = row['prefix'] + (folder.rstrip('/')+'/' if folder else '')
            if row['provider']=='s3':
                import boto3
                from botocore.config import Config
                session = boto3.Session(profile_name=row['profile'] or None, region_name=row['region'] or None)
                with session.client('s3', config=Config(connect_timeout=8,read_timeout=15,retries={'max_attempts':1})) as client:
                    args = dict(Bucket=row['bucket'], Prefix=prefix, Delimiter='/', MaxKeys=100)
                    if cursor:
                        args['ContinuationToken']=cursor
                    page = client.list_objects_v2(**args)
                items = [{'name':p['Prefix'][len(prefix):].rstrip('/'), 'path':p['Prefix'][len(row['prefix']):].rstrip('/'), 'folder':True,'size':None} for p in page.get('CommonPrefixes',[])]
                items += [{'name':o['Key'][len(prefix):], 'path':o['Key'][len(row['prefix']):], 'folder':False,'size':o['Size']} for o in page.get('Contents',[]) if o['Key']!=prefix]
                return {'items':items,'next_cursor':page.get('NextContinuationToken')}
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import ContainerClient, BlobPrefix
            with DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
                with ContainerClient(account_url=f"https://{row['account']}.blob.core.windows.net", container_name=row['container'], credential=credential, connection_timeout=8,read_timeout=15,retry_total=1) as client:
                    pages = client.walk_blobs(name_starts_with=prefix,delimiter='/',results_per_page=100).by_page(continuation_token=cursor)
                    page = next(pages, [])
                    items = [{'name':o.name[len(prefix):].rstrip('/'), 'path':o.name[len(row['prefix']):].rstrip('/'), 'folder':isinstance(o,BlobPrefix),'size':None if isinstance(o,BlobPrefix) else o.size} for o in page if o.name!=prefix]
                    return {'items':items,'next_cursor':pages.continuation_token}
        except VolumeError:
            raise
        except ImportError:
            raise VolumeError('Cloud libraries are missing. Install requirements-volumes.txt and restart the app.') from None
        except (OSError, ValueError):
            raise VolumeError('Cannot read this location. Check the path and access permissions.') from None
        except Exception:
            # Provider exceptions may contain tokens or credential details.
            raise VolumeError('Connection failed. Check the location, network, and your local cloud sign-in with permission to list this bucket or container.') from None
