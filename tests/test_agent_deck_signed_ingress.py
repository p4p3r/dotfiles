#!/usr/bin/env python3
"""Isolated signed delivery, durable receipt, and local lifecycle acceptance."""

from __future__ import annotations

import copy
import errno
import hashlib
import hmac
import importlib.machinery
import importlib.util
import json
import os
import queue
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "private_dot_local/bin/executable_agent-deck-signed-ingress"
NOW = 1_800_000_000_000
IDS = [f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 20)]
IDS[1] = "abcdefab-0000-4000-8000-000000000002"
MARKER = "SYNTHETIC_BODY_MUST_STAY_IN_HANDLER"


def load_module():
    loader = importlib.machinery.SourceFileLoader("signed_ingress", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class IngressCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.environment = patch.dict(os.environ, {
            "HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "xdg-state"),
            "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
            "XDG_RUNTIME_DIR": str(self.root / "xdg-runtime"),
            "PYTHONPYCACHEPREFIX": str(self.root / "pycache"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.mod = load_module()
        self.keys = {"github": os.urandom(32), "linear": os.urandom(32)}
        for name, value in {**self.keys, "alias": os.urandom(32)}.items():
            path = self.root / name
            path.write_bytes(value)
            path.chmod(0o600)
        owner = {"host": "fixture-host", "conductor": "0123abcd-1700000000"}
        self.config = {
            "version": 1, "owner": owner, "listen": "127.0.0.1", "port": 0,
            "state_dir": str(self.root / "state"), "runtime_dir": str(self.root / "runtime"),
            "alias_key_file": str(self.root / "alias"), "capacity": 100,
            "retention_seconds": 60,
            "github": {"path": "/github", "owner": owner.copy(),
                       "secret_file": str(self.root / "github"),
                       "actions": ["opened", "reopened", "synchronize", "edited", "closed"],
                       "repository_ids": [1001], "actor_ids": [2001]},
            "linear": {"path": "/linear", "owner": owner.copy(),
                       "secret_file": str(self.root / "linear"),
                       "actions": ["create", "update", "remove"],
                       "team_ids": [IDS[1]], "project_ids": [IDS[2]], "actor_ids": [IDS[3]]},
        }
        self.config_path = self.root / "config.json"
        self.daemons = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for daemon in reversed(self.daemons):
            daemon.close()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.config_path.chmod(0o600)

    def start(self, fault=None):
        self.write_config()
        daemon = self.mod.Daemon(self.mod.load_config(self.config_path),
                                 clock=lambda: NOW, fault=fault)
        daemon.start()
        self.daemons.append(daemon)
        return daemon

    def payload(self, provider="github"):
        if provider == "github":
            return {"action": "opened", "repository": {"id": 1001, "name": MARKER},
                    "sender": {"id": 2001, "login": MARKER},
                    "pull_request": {"id": 3001, "title": MARKER, "body": MARKER}}
        return {"action": "update", "type": "Issue", "webhookTimestamp": NOW,
                "actor": {"id": IDS[3], "name": MARKER},
                "data": {"id": IDS[0], "teamId": IDS[1], "projectId": IDS[2],
                         "title": MARKER, "description": MARKER}, "webhookId": IDS[4]}

    def packet(self, provider="github", payload=None, delivery=IDS[5], raw=None):
        body = raw if raw is not None else json.dumps(
            self.payload(provider) if payload is None else payload).encode()
        headers = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))}
        digest = hmac.new(self.keys[provider], body, hashlib.sha256).hexdigest()
        if provider == "github":
            headers.update({"X-Hub-Signature-256": "sha256=" + digest,
                            "X-GitHub-Delivery": delivery, "X-GitHub-Event": "pull_request"})
        else:
            headers.update({"Linear-Signature": digest, "Linear-Delivery": delivery,
                            "Linear-Event": "Issue", "Linear-Timestamp": str(
                                (self.payload(provider) if payload is None else payload)["webhookTimestamp"])})
        return headers, body

    def request(self, daemon, provider="github", payload=None, delivery=IDS[5],
                raw=None, updates=None, extra=(), method="POST", path=None):
        headers, body = self.packet(provider, payload, delivery, raw)
        if updates:
            headers.update(updates)
        head = f"{method} {path or '/' + provider} HTTP/1.1\r\nHost: localhost\r\n"
        head += "".join(f"{name}: {value}\r\n" for name, value in headers.items())
        head += "".join(f"{name}: {value}\r\n" for name, value in extra)
        return self.raw_request(daemon, head.encode() + b"\r\n" + body)

    def raw_request(self, daemon, packet):
        with socket.create_connection(daemon.http_address, timeout=5) as client:
            for operation in (lambda: client.sendall(packet), lambda: client.shutdown(socket.SHUT_WR)):
                try:
                    operation()
                except OSError as error:
                    if error.errno not in {errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN, errno.ECONNABORTED}:
                        raise
            chunks = []
            try:
                while data := client.recv(4096):
                    chunks.append(data)
            except ConnectionResetError:
                pass
        raw = b"".join(chunks)
        if not raw:
            return 0, {}
        head, body = raw.split(b"\r\n\r\n", 1)
        return int(head.split(b" ")[1]), json.loads(body)

    def control(self, daemon, value):
        return self.mod.control(daemon.socket_path, value)

    def rows(self, daemon):
        result = self.control(daemon, {"op": "list", "limit": 100})
        self.assertEqual(result["code"], "OK")
        return result["rows"]

    def test_valid_both_providers_body_free_aliases_and_modes(self):
        daemon = self.start()
        for provider in ("github", "linear"):
            status, result = self.request(daemon, provider)
            self.assertEqual(status, 200)
            self.assertEqual(result["code"], "ACCEPTED")
        rows = self.rows(daemon)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["provider"] for r in rows}, {"github", "linear"})
        for row in rows:
            self.assertRegex(row["event_alias"], r"^[a-z2-7]{52}$")
            self.assertRegex(row["object_alias"], r"^[a-z2-7]{52}$")
            self.assertNotEqual(row["event_alias"], row["object_alias"])
            self.assertEqual(row["state"], "accepted")
        for directory in (daemon.config.state_dir, daemon.config.runtime_dir):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            for path in directory.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(MARKER, json.dumps(rows))
        for path in daemon.config.state_dir.iterdir():
            data = path.read_bytes()
            for marker in (MARKER.encode(), IDS[0].encode(), IDS[5].encode(), b'"id": 1001'):
                self.assertNotIn(marker, data)

    def test_signature_tamper_wrong_key_and_exact_form(self):
        daemon = self.start()
        for provider, header in (("github", "X-Hub-Signature-256"), ("linear", "Linear-Signature")):
            for signature in ("", "x" * 64, "0" * 64, "sha1=" + "0" * 40,
                              "sha256=" + "0" * 65, "é" * 64):
                status, result = self.request(daemon, provider, updates={header: signature})
                self.assertNotEqual(status, 200)
                self.assertNotIn(MARKER, json.dumps(result))
            self.keys[provider] = os.urandom(32)
            self.assertNotEqual(self.request(daemon, provider)[0], 200)
        self.assertEqual(self.rows(daemon), [])

    def test_linear_skew_exact_boundaries_and_header_equality(self):
        daemon = self.start()
        for index, skew in enumerate((-60001, -60000, 60000, 60001)):
            payload = self.payload("linear")
            payload["webhookTimestamp"] += skew
            status, _ = self.request(daemon, "linear", payload, delivery=IDS[6 + index])
            self.assertEqual(status == 200, abs(skew) <= 60000)
        self.assertEqual(len(self.rows(daemon)), 2)
        for value in (str(NOW + 1), "0" + str(NOW), "+" + str(NOW), "1e12"):
            self.assertNotEqual(self.request(daemon, "linear", updates={"Linear-Timestamp": value})[0], 200)

    def test_wrong_scope_actor_provider_source_and_types_never_enqueue(self):
        daemon = self.start()
        cases = [("github", ("repository", "id"), 1002),
                 ("github", ("sender", "id"), 2002),
                 ("github", ("pull_request", "id"), True),
                 ("github", ("repository", "id"), "1001"),
                 ("linear", ("actor", "id"), IDS[7]),
                 ("linear", ("data", "teamId"), IDS[7]),
                 ("linear", ("data", "projectId"), IDS[7]),
                 ("linear", ("data", "projectId"), None),
                 ("linear", ("data", "id"), ""),
                 ("linear", ("data", "teamId"), IDS[1].upper()),
                 ("linear", ("webhookTimestamp",), True),
                 ("linear", ("type",), "Comment")]
        for provider, keys, value in cases:
            payload = self.payload(provider)
            target = payload
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            self.assertNotEqual(self.request(daemon, provider, payload)[0], 200)
        for provider in ("github", "linear"):
            payload = self.payload(provider)
            payload["action"] = "unsupported"
            self.assertNotEqual(self.request(daemon, provider, payload)[0], 200)
            self.assertNotEqual(self.request(daemon, provider, path="/unknown")[0], 200)
        payload = self.payload("linear")
        del payload["data"]["projectId"]
        self.assertNotEqual(self.request(daemon, "linear", payload)[0], 200)
        self.assertNotEqual(self.request(daemon, updates={"X-GitHub-Event": "issues"})[0], 200)
        self.assertNotEqual(self.request(daemon, "linear", delivery="00000000-0000-1000-8000-000000000006")[0], 200)
        self.assertEqual(self.rows(daemon), [])

    def test_malformed_duplicate_key_nonfinite_oversized_and_framing(self):
        daemon = self.start()
        for raw in (b"{", b"[]", b"\xff", b'{"action":"opened","action":"closed"}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'[' * 1200 + b']' * 1200):
            self.assertNotEqual(self.request(daemon, raw=raw)[0], 200)
        for updates in ({"Content-Length": "01"}, {"Content-Length": "-1"},
                        {"Content-Length": str(self.mod.MAX_BODY + 1)},
                        {"Content-Type": "text/plain"}, {"Transfer-Encoding": "chunked"},
                        {"Content-Encoding": "gzip"}, {"Expect": "100-continue"}):
            self.assertNotEqual(self.request(daemon, updates=updates)[0], 200)
        for extra in (("content-length", "0"), ("X-GitHub-Event", "pull_request"),
                      ("Host", "localhost"), ("X-Fold", "value\r\n continuation"),
                      ("X-Huge", "x" * (self.mod.MAX_HEADER_LINE + 1))):
            self.assertNotEqual(self.request(daemon, extra=(extra,))[0], 200)
        self.assertNotEqual(self.request(daemon, extra=tuple((f"X-{i}", "x") for i in range(70)))[0], 200)
        self.assertNotEqual(self.request(daemon, extra=tuple((f"X-{i}", "x" * 1500) for i in range(20)))[0], 200)
        for method in ("GET", "PUT", "DELETE", "HEAD"):
            self.assertNotEqual(self.request(daemon, method=method)[0], 200)
        for packet in (b"POST /github HTTP/1.1\r\nHost: x\r\n\r\n{}",
                       b"POST /github HTTP/1.1\nHost: x\n\n{}",
                       b"POST /github HTTP/1.1\r\nBad Header: x\r\n\r\n{}"):
            self.assertNotEqual(self.raw_request(daemon, packet)[0], 200)
        self.assertEqual(self.rows(daemon), [])

    def test_concurrent_duplicates_claim_races_replay_and_reorder(self):
        daemon = self.start()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.request(daemon), range(18)))
        self.assertTrue(all(status == 200 for status, _ in results))
        aliases = [r["event_alias"] for _, r in results]
        self.assertEqual(len(set(aliases)), 1)
        self.assertEqual(len(self.rows(daemon)), 1)
        alias = aliases[0]
        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = list(pool.map(lambda _: self.control(daemon, {"op": "claim", "event_alias": alias}), range(12)))
        self.assertEqual(sum(c["code"] == "CLAIMED" for c in claims), 1)
        before = self.rows(daemon)
        self.assertEqual(self.request(daemon)[1]["event_alias"], alias)
        self.assertEqual(self.rows(daemon), before)
        for action, delivery in (("closed", IDS[8]), ("opened", IDS[7])):
            payload = self.payload()
            payload["action"] = action
            self.assertEqual(self.request(daemon, payload=payload, delivery=delivery)[0], 200)
        self.assertEqual(len(self.rows(daemon)), 3)

    def test_concurrent_completed_retry_and_prune_keep_one_terminal_owner(self):
        daemon = self.start()
        event_alias = self.request(daemon)[1]["event_alias"]
        self.assertEqual(self.control(
            daemon, {"op": "claim", "event_alias": event_alias})["code"], "CLAIMED")
        self.assertEqual(self.control(daemon, {
            "op": "settle", "event_alias": event_alias, "result": "completed"})["code"],
            "SETTLED")
        daemon.clock = lambda: NOW + 60001
        barrier = threading.Barrier(7)

        def retry():
            barrier.wait()
            return "retry", self.request(daemon)

        def prune():
            barrier.wait()
            return "prune", self.control(daemon, {"op": "prune"})

        with ThreadPoolExecutor(max_workers=7) as pool:
            futures = [pool.submit(retry) for _ in range(6)] + [pool.submit(prune)]
            results = [future.result() for future in futures]
        self.assertEqual([value for kind, value in results if kind == "prune"],
                         [{"code": "PRUNED", "removed": 1}])
        retries = [value for kind, value in results if kind == "retry"]
        self.assertEqual(len(retries), 6)
        for status, result in retries:
            self.assertEqual(status, 200)
            self.assertEqual(result, {"code": "DUPLICATE", "event_alias": event_alias,
                                      "state": "completed", "result": "completed"})
        self.assertEqual(self.rows(daemon), [])
        self.assertEqual(self.control(
            daemon, {"op": "claim", "event_alias": event_alias})["code"], "CONFLICT")
        daemon.close()
        with closing(sqlite3.connect(
                daemon.config.state_dir / "ledger.sqlite3")) as connection:
            self.assertEqual(connection.execute(
                "SELECT event_alias,owner_host,owner_conductor,state,result "
                "FROM dedupe_tombstones").fetchall(), [
                    (event_alias, "fixture-host", "0123abcd-1700000000",
                     "completed", "completed")])

    def test_capacity_duplicate_first_and_storage_fault_no_ack(self):
        self.config["capacity"] = 1
        daemon = self.start()
        self.assertEqual(self.request(daemon)[0], 200)
        self.assertEqual(self.request(daemon)[1]["code"], "DUPLICATE")
        self.assertEqual(self.request(daemon, delivery=IDS[7])[0], 503)
        self.assertEqual(len(self.rows(daemon)), 1)
        daemon.close()
        def fail(point):
            if point == "before_commit":
                raise OSError(MARKER)
        self.config["capacity"] = 2
        daemon = self.start(fault=fail)
        self.assertEqual(self.request(daemon, delivery=IDS[7])[0], 503)
        self.assertEqual(len(self.rows(daemon)), 1)

    def test_restart_preserves_claim_uncertain_settlement_and_retention(self):
        daemon = self.start()
        aliases = []
        for delivery in IDS[6:10]:
            aliases.append(self.request(daemon, delivery=delivery)[1]["event_alias"])
        for alias, result in zip(aliases, ("completed", "api_unavailable", "dead_letter")):
            self.assertEqual(self.control(daemon, {"op": "claim", "event_alias": alias})["code"], "CLAIMED")
            self.assertEqual(self.control(daemon, {"op": "settle", "event_alias": alias, "result": result})["code"], "SETTLED")
        self.assertEqual(self.control(daemon, {"op": "claim", "event_alias": aliases[3]})["code"], "CLAIMED")
        before = self.rows(daemon)
        daemon.close()
        daemon = self.start()
        self.assertEqual(self.rows(daemon), before)
        self.assertEqual({r["state"] for r in before}, {"completed", "uncertain", "dead_letter", "claimed"})
        self.assertEqual(self.control(daemon, {"op": "claim", "event_alias": aliases[3]})["code"], "CONFLICT")
        self.assertEqual(self.control(daemon, {"op": "settle", "event_alias": aliases[3], "result": MARKER})["code"], "INVALID")
        self.assertEqual(self.control(daemon, {"op": "prune"})["removed"], 0)
        daemon.clock = lambda: NOW + 60001
        self.assertEqual(self.control(daemon, {"op": "prune"})["removed"], 1)
        self.assertEqual(len(self.rows(daemon)), 3)

    def test_strict_config_files_owner_loopback_and_key_rotation(self):
        baseline = copy.deepcopy(self.config)
        cases = [("listen", "0.0.0.0"), ("listen", "localhost"), ("listen", "::ffff:127.0.0.1"),
                 ("port", True), ("version", 2), ("capacity", 0),
                 ("alias_key_file", "relative"), ("extra", MARKER)]
        for key, value in cases:
            self.config = copy.deepcopy(baseline)
            self.config[key] = value
            self.write_config()
            with self.assertRaises(self.mod.IngressError):
                self.mod.load_config(self.config_path)
        for provider, key, value in (("github", "repository_ids", []),
                                      ("github", "actor_ids", [2001, 2001]),
                                      ("github", "actions", ["assigned"]),
                                      ("linear", "project_ids", [None]),
                                      ("linear", "owner", {"host": "other", "conductor": "0123abcd-1700000000"})):
            self.config = copy.deepcopy(baseline)
            self.config[provider][key] = value
            self.write_config()
            with self.assertRaises(self.mod.IngressError):
                self.mod.load_config(self.config_path)
        self.config = baseline
        self.write_config()
        self.config_path.write_bytes(b'{"version":1,"version":1}')
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)
        self.write_config()
        for path in (self.root / "github", self.root / "alias", self.config_path):
            path.chmod(0o644)
            with self.assertRaises(self.mod.IngressError):
                self.mod.load_config(self.config_path)
            path.chmod(0o600)
        alias_path = self.root / "alias"
        key = alias_path.read_bytes()
        alias_path.write_bytes(b"x" * 31)
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)
        alias_path.write_bytes(key)
        daemon = self.start()
        alias = self.request(daemon)[1]["event_alias"]
        daemon.close()
        self.keys["github"] = os.urandom(32)
        (self.root / "github").write_bytes(self.keys["github"])
        daemon = self.start()
        self.assertEqual(self.request(daemon)[1]["event_alias"], alias)

    def test_second_writer_unsafe_state_and_control_input_fail_closed(self):
        daemon = self.start()
        with self.assertRaises(self.mod.IngressError):
            self.mod.Daemon(daemon.config).start()
        for value in ({"op": "unknown"}, {"op": "list", "limit": True},
                      {"op": "claim", "event_alias": MARKER}, {"op": "prune", "extra": MARKER}):
            self.assertEqual(self.control(daemon, value)["code"], "INVALID")
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(daemon.socket_path))
            client.sendall(b'{"op":"list","op":"prune"}\n')
            self.assertEqual(json.loads(client.recv(4096))["code"], "INVALID")
        daemon.close()
        database = daemon.config.state_dir / "ledger.sqlite3"
        database.chmod(0o644)
        with self.assertRaises(self.mod.IngressError):
            self.start()
        database.chmod(0o600)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA user_version=99")
            connection.commit()
        with self.assertRaises(self.mod.IngressError):
            self.start()

    def test_process_death_before_commit_after_commit_and_after_claim(self):
        self.write_config()
        child_code = '''import importlib.machinery, importlib.util, os, sys, time
loader = importlib.machinery.SourceFileLoader("child_ingress", sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)
def fault(point):
    if point == sys.argv[3]: os._exit(73)
daemon = module.Daemon(module.load_config(module.Path(sys.argv[2])), clock=lambda: 1800000000000, fault=fault)
daemon.start()
print(daemon.http_address[1], flush=True)
while True: time.sleep(0.1)
'''
        for point in ("before_commit", "before_ack", "after_claim"):
            process = subprocess.Popen([sys.executable, "-c", child_code, str(SCRIPT),
                                        str(self.config_path), point], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, env=os.environ.copy())
            assert process.stdout is not None and process.stderr is not None
            try:
                port = int(process.stdout.readline())
                class Endpoint:
                    http_address = ("127.0.0.1", port)
                status, _ = self.request(Endpoint())
                if point == "after_claim":
                    sock = Path(self.config["runtime_dir"]) / "control.sock"
                    rows = self.mod.control(sock, {"op": "list", "limit": 100})["rows"]
                    try:
                        self.mod.control(sock, {"op": "claim", "event_alias": rows[0]["event_alias"]})
                    except self.mod.IngressError:
                        pass
                else:
                    self.assertNotEqual(status, 200)
                process.wait(timeout=5)
                self.assertEqual(process.returncode, 73)
                self.assertNotIn(MARKER, process.stderr.read())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
                process.stderr.close()
            daemon = self.start()
            rows = self.rows(daemon)
            if point == "before_commit":
                self.assertEqual(rows, [])
            else:
                self.assertEqual(len(rows), 1)
            self.assertEqual(self.request(daemon)[0], 200)
            self.assertEqual(len(self.rows(daemon)), 1)
            if point == "after_claim":
                self.assertEqual(self.rows(daemon)[0]["state"], "claimed")
            daemon.close()
            # Give each crash scenario a fresh isolated ledger.
            for path in daemon.config.state_dir.iterdir():
                path.unlink()

    def test_overflowing_json_number_is_rejected_even_in_unused_field(self):
        daemon = self.start()
        raw = json.dumps(self.payload()).encode()[:-1] + b',"unused":1e999}'
        self.assertNotEqual(self.request(daemon, raw=raw)[0], 200)
        self.assertEqual(self.rows(daemon), [])

    def test_body_tamper_is_rejected_before_json_parse(self):
        daemon = self.start()
        headers, raw = self.packet()
        raw = raw.replace(b"opened", b"closed")
        self.assertEqual(self.request(daemon, raw=raw, updates={
            "X-Hub-Signature-256": headers["X-Hub-Signature-256"]})[0], 401)
        self.assertEqual(self.rows(daemon), [])

    def test_absolute_read_deadline_and_bounded_control(self):
        daemon = self.start()
        with socket.create_connection(daemon.http_address, timeout=5) as client:
            start = time.monotonic()
            client.sendall(b"POST /github HTTP/1.1\r\n")
            reply = client.recv(4096)
            self.assertIn(b"503", reply)
            self.assertLess(time.monotonic() - start, self.mod.READ_TIMEOUT + 1)
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect(str(daemon.socket_path))
            client.sendall(b"x" * (self.mod.MAX_CONTROL + 1))
            self.assertEqual(json.loads(client.recv(4096))["code"], "INVALID")
        self.assertEqual(self.rows(daemon), [])

    def test_alias_full_reference_length_prefix_and_restart_key_binding(self):
        daemon = self.start()
        result = self.request(daemon)[1]
        import base64
        components = (b"signed-ingress.event.v1", b"github", IDS[5].encode())
        raw = b"".join(len(c).to_bytes(4, "big") + c for c in components)
        expected = base64.b32encode(hmac.digest(
            (self.root / "alias").read_bytes(), raw, "sha256")).decode().rstrip("=").lower()
        self.assertEqual(result["event_alias"], expected)
        self.assertRegex(result["event_alias"], r"^[a-z2-7]{52}$")
        daemon.close()
        (self.root / "alias").write_bytes(os.urandom(32))
        with self.assertRaises(self.mod.IngressError):
            self.start()

    def test_object_alias_binds_provider_type_and_canonical_id(self):
        daemon = self.start()
        self.assertEqual(self.request(daemon)[0], 200)
        object_alias = self.rows(daemon)[0]["object_alias"]
        key = (self.root / "alias").read_bytes()
        expected = self.mod.alias(
            key, "signed-ingress.object.v1", "github", "pull_request", "3001")
        without_type = self.mod.alias(key, "signed-ingress.object.v1", "github", "3001")
        other_type = self.mod.alias(
            key, "signed-ingress.object.v1", "github", "Issue", "3001")
        self.assertEqual(object_alias, expected)
        self.assertNotEqual(object_alias, without_type)
        self.assertNotEqual(object_alias, other_type)

    def test_ipv4_loopback_is_the_only_configured_listener(self):
        self.config["listen"] = "::1"
        self.write_config()
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)

    def test_prune_preserves_bounded_owner_tombstone_and_retry_disposition(self):
        self.config["capacity"] = 1
        daemon = self.start()
        accepted = self.request(daemon)[1]
        event_alias = accepted["event_alias"]
        self.assertEqual(self.control(
            daemon, {"op": "claim", "event_alias": event_alias})["code"], "CLAIMED")
        self.assertEqual(self.control(daemon, {
            "op": "settle", "event_alias": event_alias, "result": "completed"})["code"],
            "SETTLED")
        daemon.clock = lambda: NOW + 60001
        self.assertEqual(self.control(daemon, {"op": "prune"}),
                         {"code": "PRUNED", "removed": 1})
        self.assertEqual(self.rows(daemon), [])
        retry = self.request(daemon)[1]
        self.assertEqual(retry, {"code": "DUPLICATE", "event_alias": event_alias,
                                 "state": "completed", "result": "completed"})
        self.assertEqual(self.control(
            daemon, {"op": "claim", "event_alias": event_alias})["code"], "CONFLICT")
        self.assertEqual(self.request(daemon, delivery=IDS[7])[0], 503)
        daemon.close()

        database = daemon.config.state_dir / "ledger.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            columns = [row[1] for row in connection.execute(
                "PRAGMA table_info(dedupe_tombstones)")]
            self.assertEqual(columns, ["event_alias", "owner_host", "owner_conductor",
                                       "state", "result"])
            tombstones = connection.execute(
                "SELECT event_alias,owner_host,owner_conductor,state,result "
                "FROM dedupe_tombstones").fetchall()
            self.assertEqual(tombstones, [(event_alias, "fixture-host",
                                           "0123abcd-1700000000", "completed", "completed")])
            connection.execute(
                "UPDATE dedupe_tombstones SET owner_host='other-host'")
            connection.commit()
        with self.assertRaises(self.mod.IngressError):
            self.start()
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "UPDATE dedupe_tombstones SET owner_host='fixture-host'")
            connection.execute("DELETE FROM dedupe_tombstones")
            connection.commit()

        daemon = self.start()
        negative = self.request(daemon)[1]
        self.assertEqual(negative["code"], "ACCEPTED")
        self.assertEqual(negative["event_alias"], event_alias)
        self.assertEqual(self.control(
            daemon, {"op": "claim", "event_alias": event_alias})["code"], "CLAIMED")

    def test_symlinks_hardlinks_unsafe_directories_and_missing_keys(self):
        self.write_config()
        target = self.root / "github"
        saved = target.read_bytes()
        target.unlink()
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)
        other = self.root / "other"
        other.write_bytes(saved)
        other.chmod(0o600)
        target.symlink_to(other)
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)
        target.unlink()
        os.link(other, target)
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)
        target.unlink()
        other.unlink()
        target.write_bytes(saved)
        target.chmod(0o600)
        directory = Path(self.config["state_dir"])
        directory.mkdir(mode=0o755)
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)
        directory.chmod(0o700)
        directory.rmdir()
        directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(self.mod.IngressError):
            self.mod.load_config(self.config_path)

    def test_owner_change_and_unsafe_socket_fail_without_requeue(self):
        daemon = self.start()
        alias = self.request(daemon)[1]["event_alias"]
        self.assertEqual(self.control(daemon, {"op": "claim", "event_alias": alias})["code"], "CLAIMED")
        daemon.socket_path.chmod(0o666)
        with self.assertRaises(self.mod.IngressError):
            self.control(daemon, {"op": "list", "limit": 100})
        daemon.socket_path.chmod(0o600)
        daemon.close()
        for area in ("owner", "github", "linear"):
            target = self.config[area] if area == "owner" else self.config[area]["owner"]
            target["host"] = "other-host"
        with self.assertRaises(self.mod.IngressError):
            self.start()

    def test_cli_control_is_body_free_and_never_opens_ledger(self):
        daemon = self.start()
        alias = self.request(daemon)[1]["event_alias"]
        command = [sys.executable, str(SCRIPT), "--socket", str(daemon.socket_path)]
        for args in (["list"], ["claim", alias], ["settle", alias, "--result", "api_unavailable"]):
            process = subprocess.run(command + args, capture_output=True, text=True,
                                     timeout=5, env=os.environ.copy(), check=False)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertNotIn(MARKER, process.stdout + process.stderr)
        process = subprocess.run(command + ["settle", alias, "--result", MARKER],
                                 capture_output=True, text=True, timeout=5, env=os.environ.copy(), check=False)
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn(MARKER, process.stdout + process.stderr)
        self.assertEqual(self.rows(daemon)[0]["state"], "uncertain")

    def test_extra_body_column_fails_restart_without_marker_output(self):
        daemon = self.start()
        self.assertEqual(self.request(daemon)[0], 200)
        daemon.close()
        database = daemon.config.state_dir / "ledger.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("ALTER TABLE events ADD COLUMN body TEXT")
            connection.execute("UPDATE events SET body=?", (MARKER,))
            connection.commit()
        self.assertIn(MARKER.encode(), database.read_bytes())
        restarted = self.mod.Daemon(daemon.config, clock=lambda: NOW)
        try:
            with self.assertRaises(self.mod.IngressError):
                restarted.start()
        finally:
            restarted.close()
        self.assertFalse(restarted.socket_path.exists())
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(self.config_path), "serve"],
            capture_output=True, text=True, timeout=5, env=os.environ.copy(), check=False)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertEqual(process.stderr, "ERROR: UNAVAILABLE\n")
        self.assertNotIn(MARKER, process.stdout + process.stderr)
        artifacts = [path for path in self.root.rglob("*")
                     if path.is_file() and path != database]
        self.assertTrue(artifacts)
        for path in artifacts:
            self.assertNotIn(MARKER.encode(), path.read_bytes())

    def test_control_list_projects_only_bounded_body_free_columns(self):
        """Direct listing exercises the projection behind the startup schema guard."""
        daemon = self.start()
        for delivery in IDS[5:7]:
            self.assertEqual(self.request(daemon, delivery=delivery)[0], 200)
        expected = set(self.rows(daemon)[0])
        self.assertEqual(len(expected), 15)
        daemon.close()
        with closing(sqlite3.connect(daemon.config.state_dir / "ledger.sqlite3")) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("ALTER TABLE events ADD COLUMN body TEXT")
            connection.execute("UPDATE events SET body=?", (MARKER,))
            connection.commit()
            result = daemon.writer.execute(connection, self.mod.Job("list", 1, queue.Queue(1)))
        self.assertEqual(result["code"], "OK")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(set(result["rows"][0]), expected)
        self.assertNotIn(MARKER, json.dumps(result))

    def test_changed_schema_contracts_fail_closed(self):
        daemon = self.start()
        daemon.close()
        database = daemon.config.state_dir / "ledger.sqlite3"
        baseline = database.read_bytes()
        with closing(sqlite3.connect(database)) as connection:
            table_sql = connection.execute("SELECT sql FROM sqlite_schema WHERE name='events'").fetchone()[0]
            index_sql = connection.execute("SELECT sql FROM sqlite_schema WHERE name='completed_retention'").fetchone()[0]
        changes = {
            "name": table_sql.replace("received_at", "renamed_received_at"),
            "missing": table_sql.replace("    action TEXT NOT NULL,\n", "").replace(
                "action IN", "event IN"),
            "order": table_sql.replace(
                "version INTEGER NOT NULL CHECK(version=2),\n    provider TEXT NOT NULL CHECK(provider IN ('github','linear'))",
                "provider TEXT NOT NULL CHECK(provider IN ('github','linear')),\n    version INTEGER NOT NULL CHECK(version=2)"),
            "type": table_sql.replace("version INTEGER", "version TEXT"),
            "nullable": table_sql.replace("action TEXT NOT NULL", "action TEXT"),
            "default": table_sql.replace("action TEXT NOT NULL", "action TEXT NOT NULL DEFAULT 'opened'"),
            "primary_key": table_sql.replace("event_alias TEXT PRIMARY KEY", "event_alias TEXT NOT NULL"),
            "constraint": table_sql.replace("CHECK(version=2)", "CHECK(version>=1)"),
            "strict": table_sql.removesuffix(" STRICT"),
        }
        self.assertEqual(len(changes), 9)
        self.assertTrue(all(sql != table_sql for sql in changes.values()))
        for name in (*changes, "missing_index", "changed_index", "tombstone_extra_column"):
            with self.subTest(contract=name):
                database.write_bytes(baseline)
                with closing(sqlite3.connect(database)) as connection:
                    if name == "tombstone_extra_column":
                        connection.execute(
                            "ALTER TABLE dedupe_tombstones ADD COLUMN body TEXT")
                    else:
                        connection.execute("DROP TABLE events")
                        connection.execute(changes.get(name, table_sql))
                        if name != "missing_index":
                            connection.execute(index_sql if name != "changed_index" else
                                               "CREATE INDEX completed_retention ON events(accepted_at,event_alias)")
                    connection.commit()
                restarted = self.mod.Daemon(daemon.config, clock=lambda: NOW)
                try:
                    with self.assertRaises(self.mod.IngressError):
                        restarted.start()
                finally:
                    restarted.close()
                self.assertFalse(restarted.socket_path.exists())

    def test_rejection_client_collects_response_after_send_and_shutdown_errors(self):
        daemon = self.start()
        response = b'HTTP/1.1 400 Bad Request\r\n\r\n{"code":"INVALID"}'
        for send_error, shutdown_error in (
                (BrokenPipeError(errno.EPIPE, "synthetic"), OSError(errno.ENOTCONN, "synthetic")),
                (None, ConnectionResetError(errno.ECONNRESET, "synthetic"))):
            with self.subTest(send=send_error is not None), patch("socket.create_connection") as connect:
                client = connect.return_value.__enter__.return_value
                client.sendall.side_effect = send_error
                client.shutdown.side_effect = shutdown_error
                client.recv.side_effect = [response, ConnectionResetError(errno.ECONNRESET, "synthetic")]
                self.assertEqual(self.raw_request(daemon, b"synthetic"), (400, {"code": "INVALID"}))
                client.shutdown.assert_called_once_with(socket.SHUT_WR)
        with patch("socket.create_connection") as connect:
            client = connect.return_value.__enter__.return_value
            client.sendall.side_effect = OSError(errno.EINVAL, "synthetic")
            with self.assertRaises(OSError):
                self.raw_request(daemon, b"synthetic")

    def test_oversized_header_rejection_race(self):
        daemon = self.start()
        cases = ((('X-Huge', 'x' * (self.mod.MAX_HEADER_LINE + 1)),),
                 tuple((f"X-{i}", "x") for i in range(70)),
                 tuple((f"X-{i}", "x" * 1500) for i in range(20)))
        for extra in cases:
            with self.subTest(headers=len(extra)):
                status, result = self.request(daemon, extra=extra)
                self.assertIn(status, (0, 400))
                if status:
                    self.assertEqual(result, {"code": "INVALID"})
        self.assertEqual(self.rows(daemon), [])

    def test_actual_body_above_cap_returns_413(self):
        daemon = self.start()
        raw = json.dumps(self.payload()).encode()
        raw += b" " * (self.mod.MAX_BODY + 1 - len(raw))
        self.assertEqual(len(raw), self.mod.MAX_BODY + 1)
        headers, body = self.packet(raw=raw)
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(self.request(daemon, raw=raw), (413, {"code": "OVERSIZED"}))
        self.assertEqual(self.rows(daemon), [])

    def test_uppercase_allowlisted_uuid_rejects_before_duplicate_admission(self):
        daemon = self.start()
        payload = self.payload("linear")
        canonical = payload["data"]["teamId"]
        self.assertIn(canonical, self.config["linear"]["team_ids"])
        self.assertNotEqual(canonical, canonical.upper())
        self.assertEqual(self.request(daemon, "linear", payload)[0], 200)
        before = self.rows(daemon)
        payload["data"]["teamId"] = canonical.upper()
        self.assertEqual(self.request(daemon, "linear", payload), (400, {"code": "INVALID"}))
        self.assertEqual(self.rows(daemon), before)

    def test_invalid_signature_malformed_json_is_not_parsed(self):
        daemon = self.start()
        for provider, header in (("github", "X-Hub-Signature-256"), ("linear", "Linear-Signature")):
            raw = b"{"
            headers, _ = self.packet(provider, raw=raw)
            signature = headers[header]
            position = 7 if provider == "github" else 0
            wrong = signature[:position] + ("0" if signature[position] != "0" else "1") + signature[position + 1:]
            self.assertEqual(self.request(daemon, provider, raw=raw, updates={header: wrong}),
                             (401, {"code": "SIGNATURE"}))
        self.assertEqual(self.rows(daemon), [])


if __name__ == "__main__":
    unittest.main()
