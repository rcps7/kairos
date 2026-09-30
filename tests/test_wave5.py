"""Wave 5 tests: MCP server, Google connector, browser actions, agent settings."""

from unittest import mock

from kairos import mcp_server, toolkit
from kairos.connectors import google


def test_mcp_server_handle():
    tools = mcp_server._handle("tools/list", {})["tools"]
    names = [t["name"] for t in tools]
    assert "kairos_info" in names and "web_search" in names
    out = mcp_server._handle("tools/call", {"name": "kairos_info"})
    assert "Kairos" in out["content"][0]["text"]


def test_google_connector():
    cfg = {"connectors": {"google": {"enabled": True, "token": None}}}
    fake = mock.Mock(status_code=200)
    fake.json.return_value = {"files": [
        {"id": "x", "name": "report.docx", "mimeType": "application/msword",
         "webViewLink": "http://x"}]}
    with mock.patch("kairos.config.load_config", return_value=cfg), \
         mock.patch("kairos.config._keyring_get", return_value="tok"), \
         mock.patch("kairos.connectors.google.httpx.get", return_value=fake):
        out = google.search_files("report")
        assert "report.docx" in out


def test_browser_action_tool_present():
    names = [t["function"]["name"] for t in toolkit.TOOL_SCHEMAS]
    assert "browser_action" in names and "google_search" in names
