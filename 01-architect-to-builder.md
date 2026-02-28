# Architect Design Specification: Chat Panel Input Fix

## Problem Analysis

The chat input field is not accepting text. Slash commands work (submit event), but typing doesn't register. Root causes identified:

1. **Missing Focus Management**: Input widget created but never focused, so key events don't reach it
2. **Placeholder Chat Completion**: `_handle_chat()` only echoes instead of calling LM Studio API
3. **No Streaming Support**: UI can't display partial responses as they arrive
4. **Missing `chat_completion` method**: API client lacks the actual chat endpoint

## Design Specification

### 1. Event Flow Architecture

```
User Types Key
    ↓
Input Widget (has focus?) ← FIX: Call focus() on mount
    ↓
Textual captures → Input.value updated
    ↓
User presses Enter
    ↓
on_input_submitted triggered
    ↓
_handle_chat() or _handle_command()
    ↓
Chat message added to reactive history
    ↓
Update UI via watch callback
```

### 2. Focus Fix (Critical)

**Location**: `chat_panel.py` → `on_mount()`

```python
def on_mount(self) -> None:
    """Mount panel and set up watchers."""
    self._add_message("system", "Welcome! Chat with a loaded model or use /commands.")
    self._update_history_display()
    # FIX: Set focus on input so typing works immediately
    if self._input_widget:
        self._input_widget.focus()
```

### 3. State Management

Current `_chat_history` is a Textual reactive list. This is correct for local component state.

**No changes needed** - the reactive pattern works:
- `_chat_history: reactive[list[tuple[str, str]]] = reactive(list)`
- Textual automatically re-renders when `.append()` or assignment happens
- `_update_history_display()` renders from self._chat_history

### 4. API Integration

#### 4.1 Add `chat_completion` method to `LMStudioClient`

**Location**: `src/lmstudio_tui/api/client.py`

```python
async def chat_completion(
    self,
    model_id: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = -1,
    stream: bool = True,
) -> AsyncGenerator[str, None]:
    """Send chat completion request with streaming support.
    
    Uses LM Studio's /v1/chat/completions endpoint (OpenAI-compatible).
    Yields text chunks as they arrive for real-time display.
    
    Args:
        model_id: The model identifier to use
        messages: List of message dicts with "role" and "content" keys
        temperature: Sampling temperature (0.0 - 2.0)
        max_tokens: Max tokens to generate (-1 for no limit)
        stream: Whether to stream the response
        
    Yields:
        Text chunks as they arrive from the API
    """
```

#### 4.2 Streaming Protocol

LM Studio uses OpenAI-compatible streaming:
- POST to `/v1/chat/completions`
- `stream: true` in body
- Response: `data: {"choices": [{"delta": {"content": "..."}}]}`
- Terminates with `data: [DONE]`

### 5. UI Update Flow for Streaming

```
_handle_chat() called
    ↓
Add "user" message to history
    ↓
Add "assistant" placeholder to history with empty content
    ↓
Start streaming API call
    ↓
For each chunk:
    ├── Append to assistant's message content
    ├── Update _chat_history (reactive triggers UI update)
    └── Yield control for UI refresh
    ↓
Stream complete → Final update
```

### 6. Async Pattern

**Critical**: `_handle_chat()` must be async and use `async for`

```python
async def _handle_chat(self, message: str) -> None:
    # ... setup ...
    
    full_response = ""
    assistant_message_index = len(self._chat_history) - 1
    
    try:
        async for chunk in client.chat_completion(active_model, conversation):
            full_response += chunk
            # Update in-place
            self._chat_history[assistant_message_index] = ("assistant", full_response)
            self._update_history_display()
    except Exception as e:
        self._add_message("error", f"API error: {e}")
```

### 7. Message History Format

Current: `list[tuple[str, str]]` where role is "user" | "assistant" | "system" | "error"

This is correct. For API calls, convert to:
```python
conversation = [
    {"role": role, "content": content}
    for role, content in self._chat_history
    if role in ("user", "assistant")  # Only send actual chat messages
]
```

### 8. Interface Definitions

#### Store Integration (No changes needed)
```python
store.active_model.value  # Current model ID
store.models.value        # List of ModelInfo
store.api_client          # LMStudioClient instance
```

#### API Client Additions
```python
class LMStudioClient:
    # ... existing methods ...
    
    async def chat_completion(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        ...
```

#### ChatPanel Updates
```python
class ChatPanel:
    # ... existing ...
    
    def on_mount(self) -> None:
        # ADD: self._input_widget.focus()
        ...
    
    async def _handle_chat(self, message: str) -> None:
        # REPLACE placeholder with actual implementation
        ...
```

## Implementation Checklist for Builder

### Phase 1: Focus Fix (Get typing working)
- [ ] Add `self._input_widget.focus()` in `on_mount()`
- [ ] Verify input accepts text

### Phase 2: API Client
- [ ] Add `chat_completion()` method to `LMStudioClient`
- [ ] Support streaming response parsing
- [ ] Handle SSE (text/event-stream) format
- [ ] Error handling for network/API failures

### Phase 3: Chat Handler
- [ ] Implement `_handle_chat()` with streaming
- [ ] Build conversation history from _chat_history
- [ ] Add placeholder assistant message
- [ ] Iterate through stream and update UI
- [ ] Handle errors gracefully

### Phase 4: Polish
- [ ] Remove "Thinking..." placeholder (streaming replaces it)
- [ ] Ensure scroll-to-bottom on new messages
- [ ] Add typing indicator during stream

## Testing Strategy

1. **Unit Test**: Mock client.chat_completion to yield "Hello" → verify UI updates
2. **Integration**: Start app, type message → verify appears in history
3. **End-to-End**: With LM Studio running, send message → verify streaming response

## Success Criteria

1. ✅ Input field accepts text immediately on app start
2. ✅ Enter sends message to API
3. ✅ User message appears in chat history
4. ✅ Assistant response streams in character-by-character
5. ✅ Conversation persists across interactions
6. ✅ Error messages display in red

---

**Next Step**: Builder implements Phase 1 & 2, then Validator tests.
