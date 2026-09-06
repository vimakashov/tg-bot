# Design: Streaming AI responses via Rich Messages (Chat Pattern)

## Context
The current Guest Mode implementation in this Telegram bot uses the "Inline Reply" pattern. It responds to a `@bot mention` by calling `answer_guest_query`, which creates an inline message. The bot then streams the AI response by progressively calling `edit_inline_message_text` on that specific message.

While this works, the user has requested the implementation of the new **`sendRichMessage`** capabilities from Bot API 10.1. Using `sendRichMessage` requires a shift from the "Inline Reply" pattern to the "Chat Message" pattern. This design proposes this transition to provide a more native "ChatGPT-like" streaming experience directly in the chat flow.

## Objective
Implement a new streaming mechanism for Guest Mode that uses `sendRichMessageDraft` for the streaming phase and `sendRichMessage` for the finalization phase, resulting in a standard, rich-formatted chat message.

## Architecture & Components

### 1. Telegram API (`bot/telegram/api.py`)
Add support for the new Rich Message methods:
- `send_rich_message_draft(chat_id, draft_id, text)`: Calls `sendRichMessageDraft`. Used for the ephemeral streaming phase.
- `send_rich_message(chat_id, text)`: Calls `sendRichMessage`. Used to finalize the message and persist it in the chat.

### 2. Guest Mode Orchestration (`bot/telegram/guest.py`)
Rewrite the `handle_guest_message` flow to move from "answering" an inline query to "sending" a chat message:
- **Initialization:**
    - Extract `chat_id` and `user_id` from the `guest_message`.
    - Generate a unique, non-zero `draft_id` for this interaction session using a robust 64-bit integer (e.g., `int(time.time_ns())`) to prevent collisions and ensure API compatibility.
- **Streaming Loop:**
    - Iterate over chunks from the `ai.stream_completion` generator.
    - For each chunk (or batch of chunks), call `api.send_rich_message_draft(chat_id, draft_id, current_accumulated_text)`.
- **Finalization:**
    - Once the stream is exhausted, call `api.send_rich_message(chat_id, full_text)` to "anchor" the message in the chat.
    - If `send_rich_message` fails due to a transient error (network/API), attempt a single retry or fallback to a standard `api.send_message(chat_id, full_text)` to ensure the message is persisted and anchored.
- **Persistence:**
    - Only append the message to the SQLite history (`store.append`) after the successful completion of the finalization phase (either `send_rich_message` or its fallback `send_message`).
    - **Note on failure:** If `store.append` fails after a successful Telegram API call, the bot will log a warning. In this scenario, a "ghost message" exists (visible to the user but missing from the bot's history). We prioritize the user-facing response over database consistency.

### 3. AI Client (`bot/ai/groq_client.py`)
- No changes required. The existing `stream_completion` async generator is sufficient.

## Data Flow

1. `guest_message` update received.
2. `store.get_history` retrieves context.
3. `ai.stream_completion` starts yielding text chunks.
4. `api.send_rich_message_draft` is called repeatedly with the growing text, using the session-specific `draft_id`.
5. `ai.stream_completion` finishes.
6. `api.send_rich_message` is called with the full text to "anchor" the message in the chat.
7. `store.append` saves the interaction.

## Error Handling & Fallbacks

- **Streaming Interruption:** If `send_rich_message_draft` fails (e.g., due to network/API issues), the bot will attempt to "flush" the current accumulated text immediately via a single **plain** `api.send_message` call to ensure the user receives the partial answer, even if rich formatting fails.
- **AI Generation Failure:** If the `ai.stream_completion` stream raises an exception, the bot sends the `FALLBACK_TEXT` via a standard `sendMessage` (or `send_rich_message` with fallback) to notify the user.
- **Finalization (Anchor) Failure:** If the final `send_rich_message` fails, the bot will attempt to fallback to a standard `sendMessage` to ensure the user receives the final response.
- **Rich Formatting Rejection:** If `send_rich_message` fails due to invalid rich content, the bot will fallback to a plain-text `sendMessage` call.
- **Concurrency:** Multiple updates in the same chat are processed sequentially to prevent interleaved or conflicting `draft_id` updates.

## Testing Plan

1. **Unit Tests (`tests/test_api.py`):**
    - Verify `send_rich_message_draft` and `send_rich_message` generate correct JSON payloads for the Bot API.
2. **Integration Tests (`tests/test_guest.py`):**
    - Mock the AI stream and verify that `handle_guest_message` correctly triggers the sequence: `send_rich_message_draft` $\rightarrow$ `send_rich_message`.
    - Verify that the interaction is only persisted to `store` after the finalization phase succeeds.
    - **Explicitly test the "flush" logic:** Simulate a `TelegramError` during a `send_rich_message_draft` call and verify that the bot immediately attempts to finalize the current buffer via a plain `api.send_message` call.
    - **Test finalization fallback:** Simulate a failure in `send_rich_message` and verify the fallback to `send_message` works.
    - **Concurrency test:** Simulate rapid-succession updates in the same chat and verify they are handled sequentially without `draft_id` collisions.
3. **Manual Verification:**
    - Confirm that the resulting message appears as a standard chat message with rich formatting (headings, tables, etc.) rather than an inline-message reply.
