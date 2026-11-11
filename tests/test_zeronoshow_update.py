"""Mise à jour automatique du pont : empreinte, application sûre, jamais pendant un envoi/appel."""

from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from telelink import zeronoshow_update as up
from telelink.phone_link_dial import UI_LOCK


def make_bundle(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


BASE = {
    "telelink/__init__.py": b"__version__ = '1'\n",
    "telelink/zeronoshow_bridge.py": b"# pont v1\n",
    "requirements.txt": b"PyYAML\n",
}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel, data in BASE.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(data)
        (self.root / "config.yaml").write_text("secret: garde-moi\n")
        (self.root / "data").mkdir()
        (self.root / "data" / "sent.jsonl").write_text("historique\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_update(self, bundle: bytes, remote: str):
        return up.check_and_update({"url": "x", "token": "y"}, post=lambda s, p, d: {"version": remote},
                                   download=lambda s: bundle, root=self.root, log=lambda m: None)

    def test_same_version_does_nothing(self):
        self.assertEqual(self.run_update(b"", up.local_version(self.root)), "a_jour")

    def test_update_replaces_code_keeps_config_and_data(self):
        new = {**BASE, "telelink/zeronoshow_bridge.py": b"# pont v2\n", "telelink/nouveau.py": b"x = 1\n",
               "config.yaml": b"secret: ECRASE\n", "data/sent.jsonl": b"ECRASE\n", "../hors.py": b"danger\n"}
        self.assertEqual(self.run_update(make_bundle(new), "v2"), "mis_a_jour")
        self.assertEqual((self.root / "telelink/zeronoshow_bridge.py").read_bytes(), b"# pont v2\n")
        self.assertTrue((self.root / "telelink/nouveau.py").exists())
        self.assertEqual((self.root / "config.yaml").read_text(), "secret: garde-moi\n")
        self.assertEqual((self.root / "data/sent.jsonl").read_text(), "historique\n")
        self.assertFalse((self.root.parent / "hors.py").exists())
        backups = list((self.root / "data").glob("backup-maj-*/telelink/zeronoshow_bridge.py"))
        self.assertEqual(backups[0].read_bytes(), b"# pont v1\n")
        self.assertEqual((self.root / "data/version_pont.txt").read_text(), "v2")
        self.assertEqual(self.run_update(b"", "v2"), "a_jour")  # déjà appliquée : pas de retéléchargement

    def test_incomplete_bundle_is_refused(self):
        r = self.run_update(make_bundle({"telelink/autre.py": b"x"}), "v3")
        self.assertTrue(r.startswith("erreur:"))
        self.assertEqual((self.root / "telelink/zeronoshow_bridge.py").read_bytes(), b"# pont v1\n")

    def test_never_during_a_send_or_call(self):
        with UI_LOCK:
            import threading

            out = {}
            t = threading.Thread(target=lambda: out.setdefault("r", self.run_update(make_bundle(BASE), "v9")))
            t.start()
            t.join()
        self.assertEqual(out["r"], "occupe")

    def test_fingerprint_ignores_data_venv_config(self):
        v = up.local_version(self.root)
        (self.root / "data" / "autre.txt").write_text("x")
        (self.root / "config.yaml").write_text("autre")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "x.py").write_text("x")
        self.assertEqual(up.local_version(self.root), v)


if __name__ == "__main__":
    unittest.main()


class AnnouncedVersionTests(unittest.TestCase):
    def test_announces_recorded_version_despite_extra_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "telelink").mkdir()
            (root / "telelink" / "__init__.py").write_text("x")
            (root / "dump.txt").write_text("fichier propre à ce PC")
            (root / "data").mkdir()
            (root / "data" / "version_pont.txt").write_text("9e55fa87f30900f8\n")
            self.assertEqual(up.announced_version(root), "9e55fa87f30900f8")

    def test_without_record_falls_back_to_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "telelink").mkdir()
            (root / "telelink" / "__init__.py").write_text("x")
            self.assertEqual(up.announced_version(root), up.local_version(root))
