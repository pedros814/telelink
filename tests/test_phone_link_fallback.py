"""Unit tests for telelink.phone_link_fallback."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from telelink import phone_link_fallback as plf


class PathFilterTests(unittest.TestCase):
    def test_accepts_valid_contacts_db_path(self) -> None:
        path = Path(
            r"C:\Users\x\AppData\Local\Packages\Microsoft.YourPhone_abc"
            r"\LocalCache\Indexed\guid\System\Database\contacts.db"
        )
        self.assertTrue(plf._is_phone_link_db_path(path, "contacts.db"))

    def test_rejects_wrong_package_root(self) -> None:
        path = Path(
            r"C:\Users\x\AppData\Local\Packages\Some.Other.App"
            r"\LocalCache\Indexed\guid\System\Database\contacts.db"
        )
        self.assertFalse(plf._is_phone_link_db_path(path, "contacts.db"))


class FallbackDisabledTests(unittest.TestCase):
    def test_contacts_fallback_not_called_when_disabled(self) -> None:
        config = {"phone_link": {"fallback": {"enabled": False}}}
        with mock.patch.object(plf, "_find_paths") as find_mock:
            result = plf.fallback_find_contacts_databases(config=config)
        find_mock.assert_not_called()
        self.assertEqual(result, [])

    def test_contacts_fallback_uses_powershell_by_default(self) -> None:
        config = {"phone_link": {"fallback": {"enabled": True}}}
        with mock.patch.object(plf, "_powershell_find", return_value=[]) as ps_mock:
            plf.fallback_find_contacts_databases(config=config)
        ps_mock.assert_called_once()

    def test_python_engine(self) -> None:
        config = {"phone_link": {"fallback": {"enabled": True, "engine": "python"}}}
        with mock.patch.object(plf, "_python_find", return_value=[]) as py_mock:
            plf.fallback_find_contacts_databases(config=config)
        py_mock.assert_called_once()


class PowerShellFindTests(unittest.TestCase):
    def test_parses_stdout_and_filters_paths(self) -> None:
        valid = Path(
            r"C:\Users\x\AppData\Local\Packages\Microsoft.YourPhone_abc"
            r"\LocalCache\Indexed\guid\System\Database\contacts.db"
        )
        invalid = Path(
            r"C:\Users\x\AppData\Local\Packages\Some.App\contacts.db"
        )
        roots = [Path(r"C:\Users\x\AppData\Local\Packages\Microsoft.YourPhone_abc")]

        def _is_file(self: Path) -> bool:
            return "YourPhone" in str(self)

        with mock.patch.object(Path, "is_file", _is_file):
            with mock.patch(
                "telelink.phone_link_fallback.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=f"{valid}\n{invalid}\n",
                    stderr="",
                ),
            ):
                paths = plf._powershell_find(
                    roots,
                    file_name="contacts.db",
                    path_predicate=lambda p: plf._is_phone_link_db_path(p, "contacts.db"),
                    timeout=5.0,
                    max_results=10,
                )
        self.assertEqual(paths, [valid])


if __name__ == "__main__":
    unittest.main()
