"""Two simulated devices sharing one remote. Run: python3 -m unittest discover -s tests"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extralife import config as config_mod, engine as engine_mod, info  # noqa: E402
from extralife.backends.local import LocalBackend  # noqa: E402
from extralife.backends import rclone as rclone_mod  # noqa: E402
from extralife.context import Context, Device, Paths  # noqa: E402
from extralife.engine import Engine, plan_set, run_all  # noqa: E402
from extralife import progress as progress_mod, providers as providers_mod  # noqa: E402
from extralife.scan import FileInfo, wanted  # noqa: E402

PROFILE = """id = "testemu"
name = "Test Emulator"
processes = ["extralife-test-emu"]

[[set]]
id = "saves"
paths = ["{saves}"]
exclude = ["*.cfg"]
"""


class Device_:
    def __init__(self, root, name, make_backend):
        self.dir = root / name
        self.saves = self.dir / "saves"
        self.saves.mkdir(parents=True)
        prof = self.dir / "profiles"
        prof.mkdir()
        (prof / "testemu.toml").write_text(PROFILE)
        paths = Paths(self.dir / "cfg", self.dir / "state", shipped_profiles=prof)
        cfg = config_mod.load(paths.config_file)
        cfg["vars"]["saves"] = str(self.saves)
        cfg["providers"]["main"] = {"type": "local", "path": str(root / "remote")}
        self.ctx = Context(paths=paths, cfg=cfg, device=Device(id=name, name=name))
        self.make_backend = make_backend

    def engine(self):
        prov = providers_mod.Provider("main", "Main", "folder", self.ctx.cfg["providers"]["main"])
        return Engine(self.ctx, self.make_backend(), provider=prov)

    def run(self, mode="sync", **kw):
        return self.engine().run(mode, **kw)

    def write(self, rel, text, age=0):
        p = self.saves / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if age:
            t = time.time() - age
            os.utime(p, (t, t))

    def read(self, rel):
        p = self.saves / rel
        return p.read_text() if p.exists() else None


class EngineTests(unittest.TestCase):
    def make_backend(self):
        return LocalBackend(str(self.remote))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="extralife-test-"))
        self.remote = self.tmp / "remote"
        self.a = Device_(self.tmp, "deck-a", self.make_backend)
        self.b = Device_(self.tmp, "deck-b", self.make_backend)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ok(self, report):
        self.assertTrue(report["ok"], report["errors"])
        return report["sets"][0] if report["sets"] else {}

    def test_push_then_pull_to_second_device(self):
        self.a.write("game1.srm", "A1", age=3600)
        self.a.write("sub/game2.sav", "A2")
        self.a.write("emu.cfg", "settings")            # excluded by the profile
        s = self.ok(self.a.run())
        self.assertEqual(sorted(s["uploaded"]), ["game1.srm", "sub/game2.sav"])
        s = self.ok(self.b.run())
        self.assertEqual(sorted(s["downloaded"]), ["game1.srm", "sub/game2.sav"])
        self.assertEqual(self.b.read("game1.srm"), "A1")
        self.assertIsNone(self.b.read("emu.cfg"))
        self.assertEqual(int((self.a.saves / "game1.srm").stat().st_mtime),
                         int((self.b.saves / "game1.srm").stat().st_mtime))
        self.assertEqual(self.ok(self.a.run())["uploaded"], [])
        self.assertEqual(self.ok(self.b.run())["downloaded"], [])

    def test_change_flows_and_old_versions_are_kept(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        self.ok(self.b.run())
        self.a.write("g.srm", "v2")
        self.assertEqual(self.ok(self.a.run())["uploaded"], ["g.srm"])
        self.assertEqual(self.ok(self.b.run())["downloaded"], ["g.srm"])
        self.assertEqual(self.b.read("g.srm"), "v2")
        hist = self.a.engine().history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["files"][0]["rel"], "g.srm")
        backups = list((self.b.ctx.paths.backup_dir).rglob("g.srm"))
        self.assertEqual([p.read_text() for p in backups], ["v1"])

    def test_conflict_touches_nothing_until_resolved(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        self.ok(self.b.run())
        self.a.write("g.srm", "from A")
        self.b.write("g.srm", "from B")
        self.ok(self.a.run())
        s = self.ok(self.b.run())
        self.assertEqual(s["conflicts"], ["g.srm"])
        self.assertEqual(self.b.read("g.srm"), "from B")
        self.assertEqual(len(info.conflicts(self.b.ctx)), 1)
        self.assertEqual(self.ok(self.b.run())["conflicts"], ["g.srm"])     # stays flagged
        self.ok(self.b.run("push", only_set="testemu/saves", only_rels=["g.srm"]))
        self.assertEqual(info.conflicts(self.b.ctx), [])
        self.assertEqual(self.ok(self.a.run())["downloaded"], ["g.srm"])
        self.assertEqual(self.a.read("g.srm"), "from B")

    def test_first_sync_with_different_files_is_a_conflict(self):
        self.a.write("g.srm", "A")
        self.ok(self.a.run())
        self.b.write("g.srm", "B")
        self.assertEqual(self.ok(self.b.run())["conflicts"], ["g.srm"])
        self.ok(self.b.run("pull"))
        self.assertEqual(self.b.read("g.srm"), "A")
        self.assertEqual(info.conflicts(self.b.ctx), [])

    def test_deletes_go_to_history_and_backup(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        self.ok(self.b.run())
        (self.a.saves / "g.srm").unlink()
        self.assertEqual(self.ok(self.a.run())["remote_deleted"], ["g.srm"])
        self.assertEqual(self.ok(self.b.run())["local_deleted"], ["g.srm"])
        self.assertIsNone(self.b.read("g.srm"))
        self.assertTrue(list(self.b.ctx.paths.backup_dir.rglob("g.srm")))
        self.assertTrue(list((self.remote / "history").rglob("g.srm")))

    def test_deletes_not_propagated_when_disabled(self):
        for d in (self.a, self.b):
            d.ctx.cfg["sync"]["propagate_deletes"] = False
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        self.ok(self.b.run())
        (self.a.saves / "g.srm").unlink()
        self.assertEqual(self.ok(self.a.run())["remote_deleted"], [])
        self.assertEqual(self.ok(self.a.run())["uploaded"], [])
        self.ok(self.b.run())
        self.assertEqual(self.b.read("g.srm"), "v1")

    def test_force_pull_keeps_local_only_files(self):
        self.a.write("g.srm", "A")
        self.ok(self.a.run())
        self.b.write("g.srm", "B")
        self.b.write("only-b.srm", "B only")
        s = self.ok(self.b.run("pull"))
        self.assertEqual(s["downloaded"], ["g.srm"])
        self.assertEqual(self.b.read("only-b.srm"), "B only")
        self.assertEqual(self.ok(self.b.run())["uploaded"], ["only-b.srm"])

    def test_force_push_does_not_delete_remote_files(self):
        self.a.write("g.srm", "A")
        self.a.write("h.srm", "A")
        self.ok(self.a.run())
        self.b.write("g.srm", "B")
        self.assertEqual(self.ok(self.b.run("push"))["uploaded"], ["g.srm"])
        self.assertEqual(self.ok(self.b.run())["downloaded"], ["h.srm"])
        self.assertEqual(self.ok(self.b.run())["remote_deleted"], [])

    def test_restore_older_version(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        self.a.write("g.srm", "v2")
        self.ok(self.a.run())
        snap = self.a.engine().history()[0]["id"]
        r = self.a.engine().restore(snap, "testemu/saves", "g.srm")
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(self.a.read("g.srm"), "v1")
        self.ok(self.b.run())
        self.assertEqual(self.b.read("g.srm"), "v1")

    def test_running_emulator_is_skipped(self):
        self.a.write("g.srm", "v1")
        with mock.patch.object(engine_mod.procs, "is_running", return_value=True):
            s = self.ok(self.a.run())
            self.assertEqual(s["skipped"], "emulator is running")
            self.assertEqual(s["uploaded"], [])
            self.assertEqual(self.ok(self.a.run("push"))["uploaded"], ["g.srm"])

    def test_other_device_holding_the_lock(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        lock = {"device": "deck-b", "device_id": "deck-b", "expires": "2999-01-01T00:00:00Z"}
        (self.remote / "lock.json").write_text(json.dumps(lock))
        r = self.a.run()
        self.assertFalse(r["ok"])
        self.assertIn("deck-b is syncing", r["errors"][0])
        lock["expires"] = "2000-01-01T00:00:00Z"
        (self.remote / "lock.json").write_text(json.dumps(lock))
        self.ok(self.a.run())
        self.assertFalse((self.remote / "lock.json").exists())

    def test_dry_run_changes_nothing(self):
        self.a.write("g.srm", "v1")
        s = self.ok(self.a.run(dry_run=True))
        self.assertEqual(s["uploaded"], ["g.srm"])
        self.assertFalse((self.remote / "data").exists())
        self.assertFalse(self.a.ctx.paths.last_run_file.exists())

    def test_download_with_wrong_hash_is_not_installed(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        (self.remote / "data/testemu/saves/g.srm").write_text("tampered")
        r = self.b.run()
        self.assertFalse(r["ok"])
        self.assertIsNone(self.b.read("g.srm"))

    def test_switching_remote_never_deletes_local_saves(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        self.remote = self.tmp / "remote2"            # the user points the device at a new, empty remote
        r = self.a.run(dry_run=True)
        self.assertEqual(r["sets"][0]["local_deleted"], [])
        s = self.ok(self.a.run())
        self.assertEqual(s["local_deleted"], [])
        self.assertEqual(s["uploaded"], ["g.srm"])
        self.assertEqual(self.a.read("g.srm"), "v1")
        self.remote = self.tmp / "remote"             # and back: compared from scratch, same content, no change
        s = self.ok(self.a.run())
        self.assertEqual((s["uploaded"], s["local_deleted"], s["conflicts"]), ([], [], []))

    def test_wiped_remote_manifest_never_deletes_local_saves(self):
        self.a.write("g.srm", "v1")
        self.ok(self.a.run())
        shutil.rmtree(self.remote / "manifests")
        s = self.ok(self.a.run())
        self.assertEqual(s["local_deleted"], [])
        self.assertEqual(s["uploaded"], ["g.srm"])
        self.assertEqual(self.a.read("g.srm"), "v1")

    def test_recent_lists_newest_first(self):
        self.a.write("old.srm", "x", age=7200)
        self.a.write("new.srm", "y")
        self.ok(self.a.run())
        self.assertEqual([r["rel"] for r in info.recent(self.a.ctx)], ["new.srm", "old.srm"])


@unittest.skipUnless(rclone_mod.find_rclone(), "rclone not installed")
class RcloneEngineTests(EngineTests):
    """Same scenarios through rclone, using rclone's on-the-fly local remote (":local:/path")."""

    def make_backend(self):
        return rclone_mod.RcloneBackend(f":local:{self.remote}")


class PlanTests(unittest.TestCase):
    def fi(self, sha):
        return FileInfo(sha, 1, 1)

    def e(self, sha):
        return {"sha256": sha}

    def test_matrix(self):
        local = {"up": self.fi("2"), "same": self.fi("1"), "down": self.fi("1"), "conf": self.fi("2"),
                 "newl": self.fi("9")}
        remote = {"up": self.e("1"), "same": self.e("1"), "down": self.e("2"), "conf": self.e("3"),
                  "gone_l": self.e("1"), "newr": self.e("8")}
        base = {"up": self.e("1"), "same": self.e("1"), "down": self.e("1"), "conf": self.e("1"),
                "gone_l": self.e("1"), "gone_r": self.e("1")}
        local["gone_r"] = self.fi("1")
        p = plan_set(local, remote, base)
        self.assertEqual(sorted(p.uploads), ["newl", "up"])
        self.assertEqual(sorted(p.downloads), ["down", "newr"])
        self.assertEqual(p.remote_deletes, ["gone_l"])
        self.assertEqual(p.local_deletes, ["gone_r"])
        self.assertEqual(p.conflicts, ["conf"])


class GlobTests(unittest.TestCase):
    def test_globs(self):
        self.assertTrue(wanted("a/b/c.srm", ["**"], []))
        self.assertFalse(wanted("a/.lock", ["**"], [".lock"]))
        self.assertTrue(wanted("title/00010000/abcd/data/x.bin", ["title/00010000/*/data/**"], []))
        self.assertFalse(wanted("title/00010000/abcd/content/x.app", ["title/00010000/*/data/**"], []))
        self.assertTrue(wanted("Profiles.json", ["Profiles.json"], []))
        self.assertFalse(wanted("prod.keys", ["Profiles.json"], []))
        self.assertTrue(wanted("u/t/00000001/s.dat", ["*/*/00000001/**"], []))
        self.assertFalse(wanted("u/t/00000002/dlc", ["*/*/00000001/**"], []))
        self.assertTrue(wanted("cache/x", ["**"], []) and not wanted("cache/x", ["**"], ["cache/"]))


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_set(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.toml"
            cfg = config_mod.load(f)
            config_mod.set_key(cfg, "providers.local.type", "local")
            config_mod.set_key(cfg, "providers.local.path", 'C:\\odd "path"')
            config_mod.set_key(cfg, "sync.include_states", True)
            config_mod.set_key(cfg, "profiles.disabled", "ryujinx, xemu")
            config_mod.save(f, cfg)
            again = config_mod.load(f)
            self.assertEqual(again, cfg)
            with self.assertRaises(config_mod.ConfigError):
                config_mod.set_key(cfg, "sync.include_states", "maybe")


    def test_legacy_single_remote_becomes_a_provider(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.toml"
            f.write_text('[remote]\ntype = "rclone"\npath = "/old"\nremote = "gdrive:ExtraLife"\nargs = []\n')
            cfg = config_mod.load(f)
            self.assertNotIn("remote", cfg)
            self.assertEqual(cfg["providers"], {"rclone": {"type": "rclone", "remote": "gdrive:ExtraLife"}})


class MultiProviderTests(unittest.TestCase):
    """Device A syncs with two folders, device B only with the second one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="extralife-test-"))
        self.r1, self.r2 = self.tmp / "r1", self.tmp / "r2"
        self.a = Device_(self.tmp, "deck-a", None)
        self.b = Device_(self.tmp, "deck-b", None)
        self.a.ctx.cfg["providers"] = {"local": {"type": "local", "path": str(self.r1)},
                                       "ssh": {"type": "local", "path": str(self.r2)}}
        self.b.ctx.cfg["providers"] = {"ssh": {"type": "local", "path": str(self.r2)}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, dev, mode="sync", **kw):
        r = run_all(dev.ctx, mode, **kw)
        self.assertTrue(r["ok"], r["errors"])
        return r

    def remote_text(self, root, rel):
        p = root / "data/testemu/saves" / rel
        return p.read_text() if p.exists() else None

    def test_every_provider_gets_the_saves_and_a_second_pass_spreads_new_ones(self):
        self.a.write("g.srm", "v1")
        r = self.sync(self.a)
        self.assertEqual([p["provider"] for p in r["providers"]], ["local", "ssh"])
        self.assertEqual((self.remote_text(self.r1, "g.srm"), self.remote_text(self.r2, "g.srm")), ("v1", "v1"))
        self.sync(self.b)
        self.b.write("g.srm", "from B")
        self.sync(self.b)                                   # only r2 has it now
        r = self.sync(self.a)
        self.assertEqual(self.a.read("g.srm"), "from B")
        self.assertEqual(self.remote_text(self.r1, "g.srm"), "from B")     # second pass pushed it to r1
        self.assertEqual([p.get("pass") for p in r["providers"]], [None, None, 2])
        self.assertTrue(list((self.r1 / "history").rglob("g.srm")))       # r1's old version was kept
        again = self.sync(self.a)
        self.assertEqual(again["summary"], {k: 0 for k in again["summary"]})

    def test_each_provider_has_its_own_state(self):
        self.a.write("g.srm", "v1")
        self.sync(self.a)
        for pid in ("local", "ssh"):
            self.assertTrue((self.a.ctx.paths.for_provider(pid).base_dir / "testemu__saves.json").exists())
        self.sync(self.a, providers=["ssh"])
        self.assertFalse((self.a.ctx.paths.state_dir / "base").exists())

    def test_progress_ends_at_100_and_never_goes_back(self):
        seen = []
        orig = progress_mod.Progress._write

        def spy(self_, force=False):
            seen.append(self_.state["percent"])
            return orig(self_, force=True)
        self.a.write("g.srm", "x" * 300000)
        self.a.write("h.srm", "y")
        with mock.patch.object(progress_mod.Progress, "_write", spy):
            self.sync(self.a)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 100)
        p = progress_mod.read(self.a.ctx.paths.progress_file)
        self.assertFalse(p["running"])
        self.assertTrue(p["ok"])
        self.assertGreater(len(set(seen)), 4)

    def test_rate_limited_progress_is_written_late_not_dropped(self):
        f = self.tmp / "progress.json"
        pr = progress_mod.Progress(f, "sync", 1)
        pr.provider(0, "x", "X")
        pr.transfer(5, 10)                      # within the rate limit: not written yet...
        time.sleep(progress_mod.MIN_WRITE_INTERVAL * 2.5)
        self.assertGreater(progress_mod.read(f)["percent"], 50)   # ...but a moment later
        pr.finish(True)

    def test_disconnect_keeps_files_and_state(self):
        self.a.write("g.srm", "v1")
        self.sync(self.a)
        self.a.ctx.paths.config_dir.mkdir(parents=True, exist_ok=True)
        res = providers_mod.disconnect(self.a.ctx, "local")
        self.assertFalse(res["removed_login"])
        self.assertEqual(list(self.a.ctx.cfg["providers"]), ["ssh"])
        self.assertEqual(self.remote_text(self.r1, "g.srm"), "v1")
        self.assertTrue(self.a.ctx.paths.for_provider("local").base_dir.is_dir())
        r = self.sync(self.a)
        self.assertEqual([p["provider"] for p in r["providers"]], ["ssh"])

    def test_old_single_state_moves_under_the_first_provider(self):
        from extralife.context import migrate_state
        root = self.a.ctx.paths.state_dir
        (root / "base").mkdir(parents=True)
        (root / "base" / "x.json").write_text("{}")
        (root / "remote.json").write_text('{"id": "r"}')
        migrate_state(self.a.ctx)
        dest = self.a.ctx.paths.for_provider("local").provider_dir
        self.assertTrue((dest / "base" / "x.json").exists())
        self.assertTrue((dest / "remote.json").exists())
        self.assertFalse((root / "base").exists())


class UpdateCheckTests(unittest.TestCase):
    def test_version_order(self):
        from extralife.util import is_newer
        self.assertTrue(is_newer("0.1.0", "0.1.0-alpha"))
        self.assertTrue(is_newer("v0.2.0", "0.1.9"))
        self.assertTrue(is_newer("0.1.0-alpha.2", "0.1.0-alpha"))
        self.assertTrue(is_newer("0.1.0-beta", "0.1.0-alpha.9"))
        self.assertTrue(is_newer("0.10.0", "0.9.0"))
        self.assertFalse(is_newer("0.1.0-alpha", "0.1.0-alpha"))
        self.assertFalse(is_newer("0.1.0-alpha", "0.1.0"))

    def test_check_is_cached_and_reports_newer(self):
        from extralife import update
        calls = []

        def fake():
            calls.append(1)
            return {"tag_name": "v99.0.0", "html_url": "https://example/rel", "body": "notes"}
        with tempfile.TemporaryDirectory() as d:
            paths = Paths(Path(d) / "c", Path(d) / "s")
            r = update.check(paths, fetch=fake)
            self.assertTrue(r["newer"])
            self.assertEqual(r["latest"], "99.0.0")
            self.assertIn("get-release.sh", r["command"])
            update.check(paths, fetch=fake)
            self.assertEqual(len(calls), 1)                  # second call answered from the cache
            update.check(paths, force=True, fetch=fake)
            self.assertEqual(len(calls), 2)


class RemoteFolderTests(unittest.TestCase):
    def test_remote_root_is_refused(self):
        from extralife.backends import BackendError
        with mock.patch.object(rclone_mod, "find_rclone", return_value="/bin/true"):
            for bad in ("gdrive:", "gdrive:/"):
                with self.assertRaises(BackendError):
                    rclone_mod.RcloneBackend(bad)
            rclone_mod.RcloneBackend("gdrive:ExtraLife")
        for bad in ("/", str(Path.home())):
            with self.assertRaises(BackendError):
                LocalBackend(bad)


class ShippedProfilesTests(unittest.TestCase):
    def test_all_shipped_profiles_load(self):
        from extralife import profiles
        errors = []
        loaded = profiles.load_profiles(Paths(Path("/nonexistent"), Path("/nonexistent")), errors)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(loaded), 20)


if __name__ == "__main__":
    unittest.main()
