import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from volumes import Volumes, VolumeError

class VolumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.folder=self.root/'corpus'
        self.folder.mkdir()
        (self.folder/'nested').mkdir()
        (self.folder/'example.eaf').write_text('sample')
        self.volumes=Volumes(self.root/'mounts.json')
    def tearDown(self):
        self.temp.cleanup()
    def test_mount_browse_persist_unmount(self):
        result=self.volumes.mount({'provider':'local','name':'Corpus','path':str(self.folder)})
        row=result['volume']
        self.assertEqual(len(result['listing']['items']),2)
        self.assertEqual(Volumes(self.volumes.path).list()[0]['id'],row['id'])
        self.assertEqual(self.volumes.browse(row['id'],'nested')['items'],[])
        with self.assertRaises(VolumeError):
            self.volumes.mount({'provider':'local','name':'Duplicate','path':str(self.folder)})
        with self.assertRaises(VolumeError):
            self.volumes.browse(row['id'],'../')
        (self.folder/'outside').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(VolumeError):
            self.volumes.browse(row['id'],'outside')
        self.volumes.unmount(row['id'])
        self.assertEqual(self.volumes.list(),[])
        self.assertTrue((self.folder/'example.eaf').exists())
    def test_open_document_and_boundaries(self):
        result=self.volumes.mount({'provider':'local','name':'Corpus','path':str(self.folder)})
        vid=result['volume']['id']
        opened=self.volumes.open_document(vid,'example.eaf')
        self.assertEqual(opened['text'],'sample')
        with self.assertRaises(VolumeError): self.volumes.open_document(vid,'../mounts.json')
        (self.folder/'escape').symlink_to(self.volumes.path)
        with self.assertRaises(VolumeError): self.volumes.open_document(vid,'escape')
        (self.folder/'binary').write_bytes(b'\x00\xff')
        self.assertEqual(self.volumes.open_document(vid,'binary')['kind'],'binary')
        (self.folder/'large').write_bytes(b'x'*(10*1024*1024+1))
        with self.assertRaises(VolumeError): self.volumes.open_document(vid,'large')

    def test_failed_mount_not_saved(self):
        with self.assertRaises(VolumeError):
            self.volumes.mount({'provider':'local','name':'Missing','path':str(self.root/'missing')})
        self.assertFalse(self.volumes.path.exists())
    def test_local_pagination(self):
        for i in range(105): (self.folder/f'f{i}').touch()
        result=self.volumes.mount({'provider':'local','name':'Corpus','path':str(self.folder)})
        first=result['listing']
        self.assertEqual(len(first['items']),100)
        second=self.volumes.browse(result['volume']['id'],cursor=first['next_cursor'])
        self.assertEqual(len(second['items']),7)
        self.assertIsNone(second['next_cursor'])
    @patch('boto3.Session')
    def test_s3_prefix_and_pages(self, session):
        client=session.return_value.client.return_value.__enter__.return_value
        client.list_objects_v2.return_value={'CommonPrefixes':[{'Prefix':'data/sub/'}],'Contents':[{'Key':'data/a.eaf','Size':15}],'NextContinuationToken':'next'}
        r=self.volumes.mount({'provider':'s3','name':'S3','bucket':'my-bucket','prefix':'data','profile':'research'})
        self.assertEqual(r['listing']['items'][0]['path'],'sub')
        self.assertEqual(r['listing']['next_cursor'],'next')
        self.volumes.browse(r['volume']['id'],'sub',cursor='page2')
        self.assertEqual(client.list_objects_v2.call_args.kwargs['Prefix'],'data/sub/')
        self.assertEqual(client.list_objects_v2.call_args.kwargs['ContinuationToken'],'page2')
    @patch('azure.storage.blob.ContainerClient')
    @patch('azure.identity.DefaultAzureCredential')
    def test_azure_listing(self, credential, container):
        client=container.return_value.__enter__.return_value
        pages=MagicMock()
        blob=MagicMock();blob.name='data/a.eaf';blob.size=12
        pages.__next__.return_value=[blob];pages.continuation_token=None
        client.walk_blobs.return_value.by_page.return_value=pages
        result=self.volumes.mount({'provider':'azure','name':'Azure','account':'corpusaccount','container':'recordings','prefix':'data'})
        self.assertEqual(result['listing']['items'][0]['name'],'a.eaf')
        self.assertEqual(client.walk_blobs.call_args.kwargs['name_starts_with'],'data/')
    @patch('boto3.Session')
    def test_provider_errors_do_not_leak_or_save(self,session):
        session.side_effect=RuntimeError('secret credential value')
        with self.assertRaises(VolumeError) as error:
            self.volumes.mount({'provider':'s3','name':'S3','bucket':'my-bucket'})
        self.assertNotIn('secret',str(error.exception))
        self.assertFalse(self.volumes.path.exists())

if __name__=='__main__':unittest.main()
