import os
import tempfile
import unittest
from unittest.mock import patch

from backend.api.gallery import _wipe_download_root


class GalleryDeleteTests(unittest.TestCase):
    def test_wipe_download_root_removes_orphan_files_and_empty_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, '分类A', 'dynamic')
            os.makedirs(nested_dir, exist_ok=True)
            file_a = os.path.join(nested_dir, 'a.webp')
            file_b = os.path.join(tmpdir, 'root-file.jpg')
            with open(file_a, 'w', encoding='utf-8') as fh:
                fh.write('x')
            with open(file_b, 'w', encoding='utf-8') as fh:
                fh.write('y')

            with patch('backend.api.gallery.DOWNLOAD_ROOT', tmpdir):
                deleted, failed = _wipe_download_root()

            self.assertEqual(deleted, 2)
            self.assertEqual(failed, 0)
            self.assertEqual(os.listdir(tmpdir), [])


if __name__ == '__main__':
    unittest.main()
