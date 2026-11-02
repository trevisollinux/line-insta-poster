import unittest

from poster import inbox
from poster.drive import DriveFile


class MontagemTest(unittest.TestCase):
    def arquivo(self, pasta):
        return DriveFile(id="abc123", name="IMG_1.jpg", mime_type="image/jpeg", pasta=pasta)

    def test_pasta_montagem_entra_so_manual(self):
        item = inbox.draft(self.arquivo("Montagem"), "https://x/IMG_1.jpg")
        self.assertIs(item["manual"], True)
        self.assertNotIn("tipo", item)

    def test_outras_pastas_seguem_publicando(self):
        item = inbox.draft(self.arquivo("bastidor"), "https://x/IMG_1.jpg")
        self.assertNotIn("manual", item)
        self.assertEqual(item["tipo"], "bastidor")
