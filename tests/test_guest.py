import pytest
from bot.telegram.guest import (
    GuestMessage, parse_guest_message, strip_bot_mention, build_messages, handle_guest_message,
    FALLBACK_TEXT,
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

    async def get_history(self, chat_id, user_id, limit):
        return list(self._history)

    async def append(self, chat_id, user_id, role, content):
        self.appended.append((role, content))


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
    def __init__(self):
        self.answers = []

    async def answer_guest_query(self, guest_query_id, text):
        self.answers.append((guest_query_id, text))


class Cfg:
    bot_username = "testbot"
    context_messages = 10
    stream_interval = 0.0
    system_prompt = TEST_PROMPT


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


async def test_handler_truncates_to_4096():
    store, ai, api = FakeStore(), FakeAI(["x" * 5000]), FakeApi()
    await handle_guest_message(_update("@testbot hi"), api, ai, store, Cfg())
    qid, text = api.answers[0]
    assert len(text) == 4096
