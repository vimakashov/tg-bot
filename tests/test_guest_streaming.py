import pytest
import time
from dataclasses import dataclass

@dataclass
class Cfg:
    bot_username: str = "testbot"
    context_messages: int = 10
    system_prompt: str = "test prompt"

class FakeApi:
    def __init__(self):
        self.calls = []
    async def send_rich_message_draft(self, chat_id, draft_id, text):
        self.calls.append(("draft", draft_id, text))
    async def send_rich_message(self, chat_id, text):
        self.calls.append(("anchor", text))
    async def send_message(self, chat_id, text):
        self.calls.append(("plain", text))
    async def answer_guest_query(self, query_id, text, rich=False):
        self.calls.append(("answer_guest", query_id, text, rich))

class FakeAI:
    def __init__(self):
        self.stream_completion = None

class FakeStore:
    def __init__(self):
        self.appended = []
    async def append(self, chat_id, user_id, role, content):
        self.appended.append((role, content))
    async def get_history(self, chat_id, user_id, limit):
        return []
    async def clear(self, chat_id, user_id):
        pass

@pytest.fixture
def fake_api():
    return FakeApi()

@pytest.fixture
def fake_ai():
    return FakeAI()

@pytest.fixture
def fake_store():
    return FakeStore()

@pytest.mark.asyncio
async def test_handle_guest_message_streaming_sequence(fake_api, fake_ai, fake_store):
    # Setup fake AI to yield chunks
    async def mock_stream(*args, **kwargs):
        for chunk in ["Hello ", "world!"]:
            yield chunk
    fake_ai.stream_completion = mock_stream
    
    from bot.telegram.guest import handle_guest_message
    
    # Create a valid update
    update = {
        "guest_message": {
            "guest_query_id": "q1",
            "chat": {"id": 1},
            "from": {"id": 1},
            "text": "@testbot hello"
        }
    }
    config = Cfg()
    
    await handle_guest_message(update, fake_api, fake_ai, fake_store, config)
    
    # Expectation: Draft for "Hello ", Draft for "Hello world!", then Anchor "Hello world!"
    # We use pytest.any for the draft_id because it's based on time
    assert any(call[0] == "draft" and call[2] == "Hello " for call in fake_api.calls)
    assert any(call[0] == "draft" and call[2] == "Hello world!" for call in fake_api.calls)
    assert any(call[0] == "anchor" and call[1] == "Hello world!" for call in fake_api.calls)

@pytest.mark.asyncio
async def test_handle_guest_message_fallback_on_error(fake_api, fake_ai, fake_store):
    # Setup fake AI to yield chunks
    async def mock_stream(*args, **kwargs):
        yield "Hello "
        yield "world!"
    fake_ai.stream_completion = mock_stream
    
    # Mock send_rich_message_draft to raise an Exception
    async def mock_draft_error(*args, **kwargs):
        raise Exception("Draft error")
    fake_api.send_rich_message_draft = mock_draft_error

    from bot.telegram.guest import handle_guest_message

    update = {
        "guest_message": {
            "guest_query_id": "q1",
            "chat": {"id": 1},
            "from": {"id": 1},
            "text": "@testbot hello"
        }
    }
    config = Cfg()

    await handle_guest_message(update, fake_api, fake_ai, fake_store, config)

    # The error happens at the first call to send_rich_message_draft.
    # At that point, full_text is "Hello ".
    # The catch block calls send_message with "Hello ".
    assert any(call[0] == "plain" and call[1] == "Hello " for call in fake_api.calls)

@pytest.mark.asyncio
async def test_history_only_on_success(fake_api, fake_ai, fake_store):
    # Setup fake AI to yield chunks
    async def mock_stream(*args, **kwargs):
        for chunk in ["Hello ", "world!"]:
            yield chunk
    fake_ai.stream_completion = mock_stream
    
    # Mock send_rich_message to raise an Exception
    async def mock_anchor_error(*args, **kwargs):
        raise Exception("Anchor error")
    fake_api.send_rich_message = mock_anchor_error

    from bot.telegram.guest import handle_guest_message

    update = {
        "guest_message": {
            "guest_query_id": "q1",
            "chat": {"id": 1},
            "from": {"id": 1},
            "text": "@testbot hello"
        }
    }
    config = Cfg()

    await handle_guest_message(update, fake_api, fake_ai, fake_store, config)

    # Since send_rich_message failed, the exception is caught.
    # Line 95 and 96 (store.append) should NOT be reached.
    assert len(fake_store.appended) == 0
