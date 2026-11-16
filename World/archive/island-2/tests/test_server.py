"""Tests for the server's link picking, accounts and sharing. Run: python3 -m unittest discover tests

Sharing is tested against a fake GitHub API on localhost; nothing leaves the machine.
"""

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "honk"))
import server  # noqa: E402


class FakeGitHub(BaseHTTPRequestHandler):
    repos, files, calls = set(), {}, []

    def log_message(self, *a):
        pass

    def reply(self, code, obj=None):
        body = json.dumps(obj or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.calls.append(("GET", self.path, self.headers.get("Authorization")))
        parts = self.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "repos":
            return self.reply(200, {"html_url": f"https://github.com/{parts[1]}/{parts[2]}"}) if parts[2] in self.repos else self.reply(404)
        if len(parts) == 5 and parts[3] == "contents":
            return self.reply(200, {"sha": "abc"}) if self.path in self.files else self.reply(404)
        self.reply(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(("POST", self.path, body))
        self.repos.add(body["name"])
        self.reply(201, {"html_url": f"https://github.com/honk/{body['name']}"})

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(("PUT", self.path, body))
        self.files[self.path] = body
        self.reply(201, {})


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gh = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=cls.gh.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.gh.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        server.DATA, server.WORKSPACE = self.tmp / "data", self.tmp / "workspace"
        server.ACCOUNTS_FILE = self.tmp / "config" / "accounts.json"
        server.GITHUB_API = f"http://127.0.0.1:{self.gh.server_address[1]}"
        proj = server.WORKSPACE / "projects" / "cloud-toy"
        (proj / ".history").mkdir(parents=True)
        (proj / "index.html").write_text("<h1>clouds</h1>")
        (proj / ".history" / "index.old.html").write_text("old")
        FakeGitHub.repos, FakeGitHub.files, FakeGitHub.calls = set(), {}, []

    def set_account(self, share="ask"):
        server.ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        server.ACCOUNTS_FILE.write_text(json.dumps({"github": {"user": "honk", "token": "secret-token", "share": share}}))

    def test_links_are_readable_and_absolute(self):
        p = server.TextExtractor()
        p.feed('<nav><a href="/menu">Main menu here</a></nav><p>See <a href="/wiki/Cloud">clouds in the sky</a>, '
               '<a href="/wiki/Special:Random">Random article</a>, <a href="#x">jump down</a>, <a href="/edit">edit</a>.</p>')
        links = server.pick_links("https://en.wikipedia.org/wiki/Sky", p.links)
        self.assertEqual(links, [{"text": "clouds in the sky", "url": "https://en.wikipedia.org/wiki/Cloud"}])

    def test_no_account_means_no_sharing(self):
        self.assertEqual(server.account_names(), [])
        with self.assertRaises(ValueError):
            server.share({"project": "cloud-toy"})

    def test_account_names_never_include_the_token(self):
        self.set_account()
        self.assertEqual(server.account_names(), ["github (honk)"])
        self.assertNotIn("secret", json.dumps(server.account_names()))

    def test_share_waits_for_approval_then_publishes(self):
        self.set_account("ask")
        r = server.share({"project": "cloud-toy", "title": "Cloud toy", "note": "clouds"})
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(FakeGitHub.calls, [])  # nothing went out yet
        out = server.outbox_decide({"id": r["id"], "action": "approve"})
        self.assertEqual(out, {"status": "published", "project": "cloud-toy", "url": "https://github.com/honk/cloud-toy"})
        self.assertEqual(server.load_outbox(), [])
        puts = [c for c in FakeGitHub.calls if c[0] == "PUT"]
        self.assertEqual([c[1] for c in puts], ["/repos/honk/cloud-toy/contents/index.html"])  # .history stays private
        self.assertEqual(FakeGitHub.calls[0][2], "Bearer secret-token")

    def test_discard_sends_nothing(self):
        self.set_account("ask")
        r = server.share({"project": "cloud-toy"})
        self.assertEqual(server.outbox_decide({"id": r["id"], "action": "discard"})["status"], "discarded")
        self.assertEqual(FakeGitHub.calls, [])

    def test_auto_share_updates_existing_files(self):
        self.set_account("auto")
        self.assertEqual(server.share({"project": "cloud-toy"})["status"], "published")
        server.share({"project": "cloud-toy"})
        last_put = [c for c in FakeGitHub.calls if c[0] == "PUT"][-1]
        self.assertEqual(last_put[2].get("sha"), "abc")
        self.assertEqual(sum(1 for c in FakeGitHub.calls if c[0] == "POST"), 1)  # the repo is made once

    def test_share_rejects_unknown_or_odd_projects(self):
        self.set_account("auto")
        for bad in ("nope", "../data", ""):
            with self.assertRaises(ValueError):
                server.share({"project": bad})


if __name__ == "__main__":
    unittest.main()


class StateVersionTest(unittest.TestCase):
    """An old page (memory format 1) must never overwrite a newer memory (format 2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)

    def tearDown(self):
        server.DATA = self.old
        self.tmp.cleanup()

    def test_older_version_is_refused(self):
        server.save_state({"v": 2, "day": 3})
        with self.assertRaises(ValueError):
            server.save_state({"v": 1, "day": 9})
        self.assertEqual(server.load_state()["day"], 3)
        server.save_state({"v": 2, "day": 4})
        self.assertEqual(server.load_state()["day"], 4)


class CodeModelSwitchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (server.DATA, server.CODE_MODEL)
        server.DATA, server.CODE_MODEL = Path(self.tmp.name), "qwen2.5-coder:14b"
        server.SETTINGS.clear()
        self.unload, server.unload = server.unload, lambda m: True

    def tearDown(self):
        server.DATA, server.CODE_MODEL = self.old
        server.unload = self.unload
        server.SETTINGS.clear()
        self.tmp.cleanup()

    def test_switch_is_remembered(self):
        self.assertTrue(server.code_model_on())
        self.assertFalse(server.set_settings({"code_model": False})["code_model_on"])
        self.assertFalse(server.code_model_on())
        server.set_settings({"code_model": True})
        self.assertTrue(server.code_model_on())
        with self.assertRaises(ValueError):
            server.set_settings({"code_model": "off"})


class OneWriterTest(unittest.TestCase):
    """Only one page lives Honk's life; pages running older code may not overwrite newer code's memory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.WRITER.update(tab="", at=0.0)

    def tearDown(self):
        server.DATA = self.old
        server.WRITER.update(tab="", at=0.0)
        self.tmp.cleanup()

    def test_second_tab_and_old_code_are_refused(self):
        server.save_state({"v": 1, "cv": 2, "day": 1, "_tab": "a"})
        with self.assertRaises(ValueError):
            server.save_state({"v": 1, "cv": 2, "day": 5, "_tab": "b"})
        with self.assertRaises(ValueError):
            server.save_state({"v": 1, "day": 7})
        server.save_state({"v": 1, "cv": 2, "day": 2, "_tab": "a"})
        self.assertEqual(server.load_state()["day"], 2)
        self.assertNotIn("_tab", server.load_state())
