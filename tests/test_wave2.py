"""Wave 2 tests: SQL tool, connectors, MCP client."""

import sys
import tempfile
from pathlib import Path
from unittest import mock

from kairos import sql_tool, mcp_client
from kairos.connectors import github

STUB = '''
import sys, json
def send(o):
    sys.stdout.write(json.dumps(o)+"\\n"); sys.stdout.flush()
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: msg=json.loads(line)
    except Exception: continue
    m=msg.get("method"); rid=msg.get("id")
    if m=="initialize":
        send({"jsonrpc":"2.0","id":rid,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"stub","version":"1"}}})
    elif m=="tools/list":
        send({"jsonrpc":"2.0","id":rid,"result":{"tools":[{"name":"echo","description":"echo","inputSchema":{"type":"object","properties":{"text":{"type":"string"}}}}]}})
    elif m=="tools/call":
        t=msg.get("params",{}).get("arguments",{}).get("text","")
        send({"jsonrpc":"2.0","id":rid,"result":{"content":[{"type":"text","text":"echo:"+t}]}})
'''


def test_sql_tool():
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    out = sql_tool.run_sql("SELECT sum(a) AS s FROM t", files={"t": str(csv)}, root=str(d))
    assert "4" in out, out
    for bad in ("DROP TABLE t", "INSERT INTO t VALUES (1)", "SELECT * FROM '/etc/passwd'"):
        try:
            sql_tool.run_sql(bad, files={"t": str(csv)}, root=str(d))
            assert False, f"should reject: {bad}"
        except Exception:
            pass


def test_github_connector():
    with mock.patch.object(github, "_get", return_value={
            "items": [{"full_name": "rcps7/kairos", "stargazers_count": 5, "description": "agent"}]}):
        out = github.search_repos("kairos")
        assert "rcps7/kairos" in out
    with mock.patch.object(github, "_get", return_value=[
            {"number": 1, "state": "open", "title": "bug"}]):
        assert "#1" in github.list_issues("rcps7/kairos")


def test_mcp_client():
    d = Path(tempfile.mkdtemp())
    stub = d / "stub_server.py"
    stub.write_text(STUB, encoding="utf-8")
    cfg = {"mcp": {"enabled": True, "servers": {
        "stub": {"command": sys.executable, "args": [str(stub)]}}}}
    with mock.patch("kairos.config.load_config", return_value=cfg):
        schemas = mcp_client.tool_schemas()
        names = [t["function"]["name"] for t in schemas]
        assert "mcp__stub__echo" in names, names
        out = mcp_client.call("mcp__stub__echo", {"text": "hi"})
        assert out == "echo:hi", out
