import subprocess
import unittest
from unittest.mock import patch
from folder_picker import choose_folder

class FolderPickerTests(unittest.TestCase):
    @patch('folder_picker.sys.platform', 'darwin')
    @patch('folder_picker.subprocess.run')
    def test_selection_and_cancel(self, run):
        run.return_value=subprocess.CompletedProcess([],0,'/tmp/My corpus/\n','')
        self.assertEqual(choose_folder()['path'],'/tmp/My corpus/')
        run.return_value=subprocess.CompletedProcess([],0,'\n','')
        self.assertTrue(choose_folder()['cancelled'])
    @patch('folder_picker.sys.platform', 'darwin')
    @patch('folder_picker.subprocess.run')
    def test_failure_releases_picker(self, run):
        run.side_effect=subprocess.TimeoutExpired('osascript',180)
        with self.assertRaises(ValueError):choose_folder()
        run.side_effect=None
        run.return_value=subprocess.CompletedProcess([],1,'','Permission denied')
        with self.assertRaisesRegex(ValueError,'permissions'):choose_folder()

if __name__=='__main__':unittest.main()
