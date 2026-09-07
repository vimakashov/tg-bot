import pytest
from bot.telegram.api import TelegramError
from bot.telegram.guest import (
    GuestMessage, parse_guest_message, strip_bot_mention, build_messages, handle_guest_message,
    FALLBACK_TEXT, CLEAR_REPLY, is_clear_command,
)

TEST_PROMPT = "You are a test assistant."


def _update(text="@testbot hello", reply=None):
    gm = {
        "guest_query_id": "q1",
        "chat": {"id": 42},
        "from": {"id": 7},
        "text": text,
    }
    if reply is not None:
        gm["reply_to_message"] = {"text": reply}
    return {"guest_message": gm}


def test_parse_returns_none_for_non_guest_update():
    assert parse_guest_message({"message": {"text": "hi"}}) is None


def test_parse_extracts_fields():
    gm = parse_guest_message(_update(reply="context here"))
    assert gm == GuestMessage(query_id="q1", chat_id=42, user_id=7,
                              text="@testbot hello", reply_text="context here")


def test_strip_bot_mention():
    assert strip_bot_mention("@testbot hello there", "testbot") == "hello there"
    assert strip_bot_mention("hey @TestBot what's up", "testbot") == "hey what's up"
    assert strip_bot_mention("no mention", "testbot") == "no mention"


def test_is_clear_command_exact():
    assert is_clear_command("/clear") is True

def test_is_clear_command_case_and_whitespace():
    assert is_clear_command("  /CLEAR  ") is True

def test_is_clear_command_after_stripping_botname_form():
    # "/clear@testbot" -> strip_bot_mention removes "@testbot" -> "/clear"
    assert is_clear_command(strip_bot_mention("/clear@testbot", "testbot")) is True

def test_is_clear_command_rejects_extra_text():
    assert is_clear_command("/clear please") is False

def test_is_clear_command_rejects_unrelated():
    assert is_clear_command("hello") is False
    assert is_clear_command("") is False


def test_build_messages_includes_system_history_reply_and_user():
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    msgs = build_messages(history, "what is 2+2", "the math question", TEST_PROMPT)
    assert msgs[0] == {"role": "system", "content": TEST_PROMPT}
    assert msgs[1:3] == history
    assert msgs[-1]["role"] == "user"
    assert "what is 2+2" in msgs[-1]["content"]
    assert "the math question" in msgs[-1]["content"]


class FakeStore:
    def __init__(self, history=None):
        self._history = history or []
        self.appended = []
        self.cleared = None

    async def get_history(self, chat_id, user_id, limit):
        return list(self._history)

    async def append(self, chat_id, user_id, role, content):
        self.appended.append((role, content))

    async def clear(self, chat_id, user_id):
        self.cleared = (chat_id, user_id)


class FakeAI:
    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error

    async def stream_completion(self, messages):
        if self._error:
            raise self._error
        for c in self._chunks:
            yield c


class FakeApi:
    def __init__(self, rich_error=None):
        self.answers = []      # (guest_query_id, text) for each successful answer
        self.rich_flags = []   # the `rich` value passed on each call, in order
        self._rich_error = rich_error
        # Image support tracking: tracks sendMessage calls made by images module
        self.image_messages = []  # list of (chat_id, text) sent via sendMessage
        # http_client stub for image resolution
        import unittest.mock
        self._http_client = unittest.mock.AsyncMock()
        self._http_client.get = unittest.mock.AsyncMock(
            side_effect=lambda url: _mock_image_response(url)
        )


def _mock_image_response(url):
    """Return a mock httpx.Response with thumbnail for the given image URL."""
    import unittest.mock
    # Extract image_id from URL like "http://test.example.com/images/abc123.json"
    parts = url.rstrip("/").split("/")
    image_id = parts[-1].replace(".json", "")
    mock_resp = unittest.mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"thumbnail": f"https://cdn.example.com/{image_id}.jpg"}
    return mock_resp


class FakeApi:
    def __init__(self, rich_error=None):
        self.answers = []      # (guest_query_id, text) for each successful answer
        self.rich_flags = []   # the `rich` value passed on each call, in order
        self._rich_error = rich_error
        # Image support tracking: tracks sendMessage calls made by images module
        self.image_messages = []  # list of (chat_id, text) sent via sendMessage
        # http_client stub for image resolution
        import unittest.mock
        self._http_client = unittest.mock.MagicMock()
        self._http_client.get = unittest.mock.AsyncMock(
            side_effect=_mock_image_response
        )

    async def answer_guest_query(self, guest_query_id, text, rich=True):
        self.rich_flags.append(rich)
        if rich and self._rich_error:
            raise self._rich_error
        self.answers.append((guest_query_id, text))

    async def call(self, method, **kwargs):
        if method == "sendMessage":
            chat_id = kwargs.get("chat_id")
            text = kwargs.get("text", "")
            self.image_messages.append((chat_id, text))


class Cfg:
    bot_username = "testbot"
    context_messages = 10
    stream_interval = 0.0
    system_prompt = TEST_PROMPT
    image_base_url = "http://test.example.com/images"


async def test_handler_accumulates_and_answers_once():
    store, ai, api = FakeStore(), FakeAI(["Hel", "lo!"]), FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())
    # guest mode: exactly one reply with the full concatenated text
    assert api.answers == [("q1", "Hello!")]
    assert store.appended == [("user", "hi"), ("assistant", "Hello!")]


async def test_handler_ignores_non_guest_update():
    store, ai, api = FakeStore(), FakeAI(["x"]), FakeApi()
    await handle_guest_message({"message": {}}, api, ai, store, Cfg())
    assert api.answers == []


async def test_handler_sends_fallback_on_ai_error():
    store, ai, api = FakeStore(), FakeAI(error=RuntimeError("groq down")), FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())
    assert api.answers == [("q1", FALLBACK_TEXT)]


async def test_handler_clear_command_resets_and_skips_ai():
    store, ai, api = FakeStore(history=[{"role": "user", "content": "old"}]), FakeAI(["should not run"]), FakeApi()
    await handle_guest_message(_update("@testbot /clear"), api, ai, store, Cfg())
    assert store.cleared == (42, 7)              # (chat_id, user_id) from _update
    assert api.answers == [("q1", CLEAR_REPLY)]  # answered exactly once
    assert store.appended == []                  # no history written


async def test_handler_truncates_to_4096():
    store, ai, api = FakeStore(), FakeAI(["x" * 5000]), FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())
    qid, text = api.answers[0]
    assert len(text) == 4096


async def test_handler_falls_back_to_plain_on_rich_rejection():
    store, ai = FakeStore(), FakeAI(["**Hi**"])
    api = FakeApi(rich_error=TelegramError("can't parse markdown"))
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())
    # rich attempted first (True), then retried as plain (False)
    assert api.rich_flags == [True, False]
    # the reply still reached the user, and history was persisted
    assert api.answers == [("q1", "**Hi**")]
    assert store.appended == [("user", "hi"), ("assistant", "**Hi**")]


async def test_handler_sends_clean_text_and_triggers_image_upload():
    """When response contains [[img:id]] placeholders, text is cleaned and image URLs are sent."""
    store, ai = FakeStore(), FakeAI(["Photo: [[img:abc123]]"])
    api = FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())

    # Clean text sent (placeholder removed)
    assert api.answers == [("q1", "Photo: ")]

    # Image URL sent as a separate message via sendMessage
    assert len(api.image_messages) == 1
    chat_id, url = api.image_messages[0]
    assert chat_id == 42  # from _update fixture
    assert "abc123" in url


async def test_handler_no_image_upload_when_no_placeholders():
    """When response has no placeholders, no image URL message is triggered."""
    store, ai = FakeStore(), FakeAI(["Hello world"])
    api = FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())

    assert api.answers == [("q1", "Hello world")]
    assert api.image_messages == []


async def test_handler_sends_multiple_images():
    """Multiple image placeholders trigger multiple URL messages."""
    store, ai = FakeStore(), FakeAI("[[img:first]] and [[img:second]]")
    api = FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())

    assert api.answers == [("q1", " and ")]
    assert len(api.image_messages) == 2
    urls = [msg[1] for msg in api.image_messages]
    assert any("first" in u for u in urls)
    assert any("second" in u for u in urls)
