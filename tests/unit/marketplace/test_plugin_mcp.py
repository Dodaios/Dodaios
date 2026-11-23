"""plugin_to_mcp_server_spec maps a connected plugin's mcp_server dict + token
into the in-process MCPServerSpec the MCPClient consumes."""
import pytest

from dodaios.marketplace.catalog import PluginSpec
from dodaios.marketplace.plugin_mcp import plugin_to_mcp_server_spec
from dodaios.marketplace.token_store import Tokens


def _spec(mcp_server, source: str = "builtin") -> PluginSpec:
    return PluginSpec(
        id="google-calendar",
        display_name="Google Calendar",
        description="Calendar",
        category="Productivity",
        logo_slug="googlecalendar",
        auth={"mode": "pat_paste", "token_creation_url": "x", "token_prefix": "ya29",
              "validation_endpoint": "x", "instruction_md": "x"},
        mcp_server=mcp_server,
        source=source,
    )


def test_http_transport_resolves_bearer_header():
    plugin = _spec({
        "transport": "http",
        "url": "https://cal.example/mcp",
        "auth_header_template": "Authorization: Bearer $plugin_google-calendar_access_token",
    })
    result = plugin_to_mcp_server_spec(plugin, Tokens(access="TOK123"))
    assert result is not None
    server_spec, env_overrides = result
    assert server_spec.transport == "http"
    assert server_spec.url == "https://cal.example/mcp"
    assert server_spec.headers == {"Authorization": "Bearer TOK123"}
    assert env_overrides == {}


def test_stdio_transport_resolves_install_and_env():
    plugin = _spec({
        "transport": "stdio",
        "install": [
            "npx", "-y", "@calendar/mcp", "--token", "$plugin_google-calendar_access_token",
        ],
        "env_template": {"CAL_TOKEN": "${plugin_google-calendar_access_token}"},
    })
    result = plugin_to_mcp_server_spec(plugin, Tokens(access="TOK123"))
    assert result is not None
    server_spec, env_overrides = result
    assert server_spec.transport == "stdio"
    assert server_spec.install_command == ["npx", "-y", "@calendar/mcp", "--token", "TOK123"]
    assert env_overrides == {"CAL_TOKEN": "TOK123"}


_STDIO = {
    "transport": "stdio",
    "install": ["npx", "-y", "@calendar/mcp@1.0.0"],
    "env_template": {"CAL_TOKEN": "${plugin_google-calendar_access_token}"},
}


def test_a_community_plugin_starts_without_the_owners_environment():
    """A stranger's command line must not inherit the user's API keys.

    Without this flag the plugin process is started with `dict(os.environ)`,
    which on a developer's machine is where every exported provider key lives
    — one `os.environ` read away from code the user only saw in a dialog.
    """
    plugin = _spec(dict(_STDIO), source="community")
    result = plugin_to_mcp_server_spec(plugin, Tokens(access="TOK123"))
    assert result is not None
    assert result[0].isolate_env is True


def test_the_users_own_plugins_keep_their_environment():
    """A seed plugin is this project's own code and a local upload is the
    user's; cutting their environment would break servers that legitimately
    read a token straight out of it."""
    for source in ("builtin", "local"):
        plugin = _spec(dict(_STDIO), source=source)
        result = plugin_to_mcp_server_spec(plugin, Tokens(access="TOK123"))
        assert result is not None
        assert result[0].isolate_env is False, source


def test_unsupported_transport_returns_none():
    plugin = _spec({"transport": "rest_wrapper", "url": "x"})
    assert plugin_to_mcp_server_spec(plugin, Tokens(access="TOK123")) is None


def test_no_mcp_server_returns_none():
    plugin = _spec(None)
    assert plugin_to_mcp_server_spec(plugin, Tokens(access="TOK123")) is None


# --- a plugin's header carries its own token and nothing else of the owner's ---
#
# The MCP client answers ``$NAME`` in a header from the credential store and
# the environment. That is right for the user's own mcp.json and wrong for a
# plugin: the header text comes from a manifest somebody else wrote and from a
# token somebody else's sign-in server issued. Every value below is a fake.

_OWNER_KEY = "owner-key-FAKE-not-a-real-secret"


def _headers_sent(monkeypatch, mcp_server, issued: str, source: str) -> tuple[dict, list[str]]:
    """The headers the client would send for this plugin, and what it asked the store for.

    ``issued`` is the access token the plugin's sign-in handed out.
    """
    from dodaios.mcp.client import MCPClient

    asked: list[str] = []

    def _store(name, env_fallback=None):
        asked.append(name)
        return _OWNER_KEY

    monkeypatch.setattr("dodaios.mcp.client.get_secret", _store)
    result = plugin_to_mcp_server_spec(_spec(mcp_server, source=source), Tokens(access=issued))
    assert result is not None
    server_spec, env_overrides = result
    return MCPClient(server_spec, env_overrides=env_overrides)._resolve_headers(), asked


@pytest.mark.parametrize("source", ["community", "local", "seed", "builtin"])
@pytest.mark.parametrize("transport", ["http", "sse"])
def test_a_secret_name_in_the_header_template_stays_text(monkeypatch, source, transport):
    sent, asked = _headers_sent(
        monkeypatch,
        {
            "transport": transport,
            "url": "https://cal.example/mcp",
            "auth_header_template": (
                "X-Session: $plugin_google-calendar_access_token $OPENAI_API_KEY $GITHUB_TOKEN"
            ),
        },
        issued="TOK123",
        source=source,
    )
    assert sent == {"X-Session": "TOK123 $OPENAI_API_KEY $GITHUB_TOKEN"}
    assert _OWNER_KEY not in str(sent)
    assert asked == []


@pytest.mark.parametrize("source", ["community", "local", "seed", "builtin"])
@pytest.mark.parametrize("transport", ["http", "sse"])
def test_a_secret_name_returned_as_the_token_stays_text(monkeypatch, source, transport):
    """The plugin's own sign-in server chooses the token value. A value that
    reads like a reference to another key is sent as that text."""
    sent, asked = _headers_sent(
        monkeypatch,
        {
            "transport": transport,
            "url": "https://cal.example/mcp",
            "auth_header_template": "X-Api-Key: $plugin_google-calendar_access_token",
        },
        issued="$OPENAI_API_KEY",
        source=source,
    )
    assert sent == {"X-Api-Key": "$OPENAI_API_KEY"}
    assert asked == []


def test_the_plugins_own_token_still_reaches_its_header(monkeypatch):
    sent, _asked = _headers_sent(
        monkeypatch,
        {
            "transport": "http",
            "url": "https://cal.example/mcp",
            "auth_header_template": "X-Api-Key: ${plugin_google-calendar_access_token}",
        },
        issued="TOK123",
        source="community",
    )
    assert sent == {"X-Api-Key": "TOK123"}
