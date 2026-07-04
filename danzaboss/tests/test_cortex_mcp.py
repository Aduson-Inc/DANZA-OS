"""C6 MCP stdio server: protocol conformance + the acceptance criterion —
an external MCP client (separate process) retrieves a CORTEX package."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _bootstrap  # noqa
from danzaboss.cortex import commands, factory
from danzaboss.cortex.mcp_server import (CortexMcpServer, PROTOCOL_VERSION,
                                         TOOLS)
from danzaboss.cortex.observation import ObsType
from danzaboss.cortex.sqlite_backend import SqliteBackend

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class McpBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        patcher = mock.patch.dict(os.environ, {
            factory.GLOBAL_DB_ENV: os.path.join(self.root, "gh", "global.db"),
            factory.GLOBAL_DSN_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.server = CortexMcpServer(self.root)

    def seed(self, title="Redis chosen for cache", **kw):
        payload = {"title": title, "summary": kw.pop("summary", "uses redis"),
                   "type": kw.pop("type", ObsType.DECISION.value), **kw}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = commands.main(["observe"], root=self.root,
                               stdin=io.StringIO(json.dumps(payload)))
        self.assertEqual(rc, 0)
        return json.loads(out.getvalue())["stored"][0]

    def call(self, method, params=None, msg_id=1):
        return self.server.handle({"jsonrpc": "2.0", "id": msg_id,
                                   "method": method, "params": params or {}})

    def call_tool(self, name, arguments=None):
        resp = self.call("tools/call", {"name": name,
                                        "arguments": arguments or {}})
        content = resp["result"]["content"][0]["text"]
        return resp["result"]["isError"], content


class TestProtocol(McpBase):
    def test_initialize_negotiates_version_and_advertises_tools(self):
        resp = self.call("initialize",
                         {"protocolVersion": PROTOCOL_VERSION,
                          "capabilities": {}, "clientInfo": {"name": "t"}})
        result = resp["result"]
        self.assertEqual(result["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(result["serverInfo"]["name"], "danza-cortex")
        self.assertIn("tools", result["capabilities"])

    def test_initialize_caps_future_client_version_to_ours(self):
        resp = self.call("initialize", {"protocolVersion": "2099-01-01"})
        self.assertEqual(resp["result"]["protocolVersion"], PROTOCOL_VERSION)

    def test_notifications_get_no_response(self):
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_ping_and_tools_list(self):
        self.assertEqual(self.call("ping")["result"], {})
        tools = self.call("tools/list")["result"]["tools"]
        self.assertEqual([t["name"] for t in tools],
                         ["cortex_search", "cortex_get", "cortex_retrieve",
                          "cortex_context"])
        self.assertIs(tools, TOOLS)

    def test_unknown_method_is_32601(self):
        self.assertEqual(self.call("resources/list")["error"]["code"], -32601)

    def test_unknown_tool_is_invalid_params(self):
        resp = self.call("tools/call", {"name": "nope"})
        self.assertEqual(resp["error"]["code"], -32602)

    def test_non_object_json_frames_do_not_kill_the_loop(self):
        out = io.StringIO()
        self.server.run(stdin=io.StringIO(
            '[]\n"hi"\n5\n'
            '{"jsonrpc":"2.0","id":8,"method":"initialize",'
            '"params":{"protocolVersion":20250618}}\n'
            '{"jsonrpc":"2.0","id":9,"method":"ping","params":[1,2]}\n'),
            stdout=out)
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([l["error"]["code"] for l in lines[:3]],
                         [-32600, -32600, -32600])
        self.assertEqual(lines[3]["result"]["protocolVersion"],
                         PROTOCOL_VERSION)  # non-string version coerced
        self.assertEqual(lines[4], {"jsonrpc": "2.0", "id": 9, "result": {}})

    def test_parse_error_emits_32700_and_loop_survives(self):
        out = io.StringIO()
        self.server.run(stdin=io.StringIO('{broken\n{"jsonrpc":"2.0","id":7,'
                                          '"method":"ping"}\n'), stdout=out)
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1], {"jsonrpc": "2.0", "id": 7, "result": {}})


class TestTools(McpBase):
    def test_search_finds_seeded_observation(self):
        oid = self.seed()
        is_error, text = self.call_tool("cortex_search", {"query": "redis"})
        self.assertFalse(is_error)
        self.assertIn(oid, [h["id"] for h in json.loads(text)])

    def test_search_without_query_is_tool_error_not_crash(self):
        is_error, text = self.call_tool("cortex_search", {})
        self.assertTrue(is_error)
        self.assertIn("query", text)

    def test_get_returns_full_row_and_records_use(self):
        oid = self.seed()
        is_error, text = self.call_tool("cortex_get", {"ids": [oid]})
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)[0]["id"], oid)
        be = SqliteBackend(factory.db_path(self.root))
        self.assertEqual(be.get(oid).usage_count, 1)
        self.assertEqual(be.usage_log()[0]["source"], "mcp")

    def test_retrieve_returns_package_with_seeded_title(self):
        self.seed(title="Redis chosen for cache",
                  summary="redis backs the session cache",
                  concepts=["redis", "cache"])
        is_error, text = self.call_tool("cortex_retrieve",
                                        {"prompt": "how is caching done?"})
        self.assertFalse(is_error)
        self.assertIn("Redis chosen for cache", text)

    def test_context_renders_index(self):
        oid = self.seed()
        is_error, text = self.call_tool("cortex_context")
        self.assertFalse(is_error)
        self.assertIn(oid, text)


class TestExternalClient(unittest.TestCase):
    """ACCEPTANCE (design §8, C6): an external MCP client — a genuinely
    separate process speaking stdio — retrieves a package."""

    def test_subprocess_client_initialize_list_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ,
                       PYTHONPATH=_REPO_ROOT,
                       DANZA_CORTEX_GLOBAL_DB=os.path.join(tmp, "g.db"),
                       DANZA_CORTEX_GLOBAL_DSN="")
            seed = subprocess.run(
                [sys.executable, "-m", "danzaboss.cli", "cortex", "observe"],
                input=json.dumps({"title": "Redis chosen for cache",
                                  "summary": "redis backs the cache",
                                  "type": "decision",
                                  "concepts": ["redis", "cache"]}),
                capture_output=True, text=True, cwd=tmp, env=env, timeout=30)
            self.assertEqual(seed.returncode, 0, seed.stderr)

            client_frames = "\n".join(json.dumps(m) for m in [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": PROTOCOL_VERSION,
                            "capabilities": {},
                            "clientInfo": {"name": "external-test-client"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "cortex_retrieve",
                            "arguments": {"prompt": "how is caching done?"}}},
            ]) + "\n"
            proc = subprocess.run(
                [sys.executable, "-m", "danzaboss.cli", "cortex", "mcp"],
                input=client_frames, capture_output=True, text=True,
                cwd=tmp, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            responses = {m["id"]: m for m in
                         (json.loads(l) for l in proc.stdout.splitlines())}
            self.assertEqual(len(responses), 3)  # notification unanswered
            self.assertEqual(
                responses[1]["result"]["serverInfo"]["name"], "danza-cortex")
            self.assertEqual(len(responses[2]["result"]["tools"]), 4)
            package = responses[3]["result"]["content"][0]["text"]
            self.assertFalse(responses[3]["result"]["isError"])
            self.assertIn("Redis chosen for cache", package)


if __name__ == "__main__":
    unittest.main()
