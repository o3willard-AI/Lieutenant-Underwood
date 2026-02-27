"""Chat and model download panel for LM Studio TUI.

Provides:
- Chat input for sanity checking loaded models
- Slash commands for model download/switch
"""

from __future__ import annotations

import logging
from typing import Optional

from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Input, Static, Button

from lmstudio_tui.store import get_store

logger = logging.getLogger(__name__)


class ChatPanel(Container):
    """Panel for chatting with loaded models and downloading new ones.
    
    Features:
    - Chat input field for sending prompts to loaded model
    - Slash commands (/download, /switch) for model management
    - Chat history display
    """

    DEFAULT_CSS = """
    ChatPanel {
        width: 100%;
        height: auto;
        padding: 1;
        border: solid $primary;
    }
    ChatPanel Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        content-align: left middle;
    }
    ChatPanel Static.chat-history {
        height: 8;
        border: solid $surface;
        padding: 0 1;
        overflow-y: auto;
    }
    ChatPanel Static.chat-message {
        height: auto;
        margin: 0;
    }
    ChatPanel Static.chat-message.user {
        color: $text;
    }
    ChatPanel Static.chat-message.assistant {
        color: $success;
    }
    ChatPanel Static.chat-message.system {
        color: $text-muted;
        text-style: italic;
    }
    ChatPanel Static.chat-message.error {
        color: $error;
    }
    ChatPanel Input {
        width: 1fr;
        margin-top: 1;
    }
    ChatPanel Static.hint {
        color: $text-muted;
        text-style: italic;
        height: 1;
        margin-top: 0;
    }
    """

    _chat_history: reactive[list[tuple[str, str]]] = reactive(list)  # (role, message)

    def __init__(self, **kwargs):
        """Initialize chat panel."""
        super().__init__(**kwargs)
        self._store = get_store()
        self._history_widget: Optional[Static] = None
        self._input_widget: Optional[Input] = None

    def compose(self):
        """Compose the chat panel widgets."""
        yield Static("💬 CHAT / DOWNLOAD", classes="title")
        
        # Chat history display
        self._history_widget = Static("", classes="chat-history")
        yield self._history_widget
        
        # Input field
        with Horizontal():
            self._input_widget = Input(
                placeholder="Type message or /command...",
                id="chat_input"
            )
            yield self._input_widget
        
        # Hint text
        yield Static("Commands: /download <key>  |  /switch <model_id>  |  Type to chat", classes="hint")

    def on_mount(self) -> None:
        """Mount panel and set up watchers."""
        # Add welcome message
        self._add_message("system", "Welcome! Chat with a loaded model or use /commands.")
        self._update_history_display()

    def _add_message(self, role: str, message: str) -> None:
        """Add a message to chat history.
        
        Args:
            role: Message role (user, assistant, system, error).
            message: Message content.
        """
        self._chat_history.append((role, message))
        # Keep only last 50 messages
        if len(self._chat_history) > 50:
            self._chat_history = self._chat_history[-50:]
        self._update_history_display()

    def _update_history_display(self) -> None:
        """Update the history widget with current messages."""
        if not self._history_widget:
            return
        
        lines = []
        for role, message in self._chat_history[-10:]:  # Show last 10
            prefix = {
                "user": "You: ",
                "assistant": "Model: ",
                "system": "ℹ️  ",
                "error": "❌ ",
            }.get(role, "")
            lines.append(f"{prefix}{message}")
        
        self._history_widget.update("\n".join(lines) if lines else "No messages yet.")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission.
        
        Args:
            event: Input submission event.
        """
        message = event.value.strip()
        if not message:
            return
        
        # Clear input
        if self._input_widget:
            self._input_widget.value = ""
        
        # Handle commands
        if message.startswith("/"):
            await self._handle_command(message)
        else:
            # Regular chat message
            await self._handle_chat(message)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands.
        
        Args:
            command: The command string (e.g., "/download <key>").
        """
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        
        if cmd == "/download":
            await self._cmd_download(arg)
        elif cmd == "/switch":
            await self._cmd_switch(arg)
        elif cmd == "/clear":
            self._chat_history.clear()
            self._add_message("system", "Chat history cleared.")
        elif cmd == "/help":
            self._add_message("system", "Commands: /download <key>, /switch <model_id>, /clear, /help")
        else:
            self._add_message("error", f"Unknown command: {cmd}")

    async def _cmd_download(self, key: str) -> None:
        """Handle /download command.
        
        Args:
            key: Model key or URL to download.
        """
        if not key:
            self._add_message("error", "Usage: /download <model_key_or_url>")
            return
        
        self._add_message("system", f"Initiating download: {key}...")
        
        try:
            client = self._store.api_client
            if not client:
                self._add_message("error", "Not connected to server")
                return
            
            # LM Studio API for downloading models
            # This is a placeholder - actual implementation depends on API availability
            logger.info(f"Download requested for: {key}")
            
            # For now, just notify user
            self._add_message("system", f"Download feature not yet implemented via API. Use LM Studio UI to download: {key}")
            
        except Exception as e:
            logger.error(f"Download failed: {e}")
            self._add_message("error", f"Download failed: {e}")

    async def _cmd_switch(self, model_id: str) -> None:
        """Handle /switch command.
        
        Args:
            model_id: Model ID to switch to.
        """
        if not model_id:
            self._add_message("error", "Usage: /switch <model_id>")
            return
        
        self._add_message("system", f"Switching to model: {model_id}...")
        
        # Set as active model
        self._store.set_active_model(model_id)
        self._add_message("system", f"Active model set to: {model_id}")
        
        # If not loaded, suggest loading
        model = None
        for m in self._store.models.value:
            if m.id == model_id:
                model = m
                break
        
        if model and not model.loaded:
            self._add_message("system", f"Model not loaded. Press 'l' in Models panel to load.")

    async def _handle_chat(self, message: str) -> None:
        """Handle regular chat message.
        
        Args:
            message: User's chat message.
        """
        self._add_message("user", message)
        
        # Get active model
        active_model = self._store.active_model.value
        if not active_model:
            self._add_message("error", "No active model selected. Select a loaded model first.")
            return
        
        # Check if model is loaded
        model_info = None
        for m in self._store.models.value:
            if m.id == active_model:
                model_info = m
                break
        
        if not model_info or not model_info.loaded:
            self._add_message("error", f"Model '{active_model}' is not loaded. Load it first.")
            return
        
        # Send to API
        try:
            client = self._store.api_client
            if not client:
                self._add_message("error", "Not connected to server")
                return
            
            # Simple completion request
            self._add_message("system", "Thinking...")
            
            # Note: This requires a completion/chat endpoint implementation
            # For now, just echo back
            logger.info(f"Chat message to {active_model}: {message}")
            
            # Placeholder: In a full implementation, this would call the chat API
            # response = await client.chat_completion(active_model, message)
            # self._add_message("assistant", response)
            
            self._add_message("assistant", f"[Echo from {active_model}]: {message}")
            
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            self._add_message("error", f"Chat failed: {e}")
