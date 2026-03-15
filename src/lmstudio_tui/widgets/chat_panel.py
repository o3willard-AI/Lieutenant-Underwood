"""Chat and model download panel for LM Studio TUI.

Provides:
- Chat input for sanity checking loaded models
- Slash commands for model download/switch
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from textual.containers import Container, Horizontal, Vertical, VerticalScroll
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
        height: 100%;
        padding: 1;
        border: solid $primary;
    }
    ChatPanel Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        content-align: left middle;
    }
    ChatPanel VerticalScroll.chat-history {
        height: 1fr;
        border: none;
        padding: 0 1;
    }
    ChatPanel VerticalScroll.chat-history:focus {
        border-left: tall $primary;
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
        margin-top: 0;
        border: none;
        height: 3;
        padding: 1 1;
    }
    ChatPanel Input:focus {
        border: none;
        background: $surface-lighten-1;
    }
    ChatPanel Static.hint {
        color: $text-muted;
        text-style: italic;
        height: 1;
        margin-top: 0;
    }
    ChatPanel Static.active-model {
        color: $text-muted;
        height: 1;
        margin-top: 0;
    }
    """

    _stream_timeout_seconds: float = 30.0  # Timeout after 30 seconds of no chunks

    def __init__(self, **kwargs):
        """Initialize chat panel."""
        super().__init__(**kwargs)
        self._store = get_store()
        self._history_widget: Optional[VerticalScroll] = None
        self._history_content: Optional[Static] = None
        self._input_widget: Optional[Input] = None
        self._active_model_widget: Optional[Static] = None
        self._current_stream_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        # Plain Python attributes — NOT Textual reactives; setting them from
        # asyncio tasks must not trigger Textual's reactive/repaint machinery.
        self._chat_history: list[tuple[str, str]] = []
        self._is_generating: bool = False
        self._last_chunk_time: float = 0.0

    def compose(self):
        """Compose the chat panel widgets."""
        yield Static("💬 CHAT", classes="title")
        self._active_model_widget = Static("", classes="active-model")
        yield self._active_model_widget

        # Chat history display (scrollable)
        with VerticalScroll(classes="chat-history") as self._history_widget:
            self._history_content = Static("", classes="chat-content")
            yield self._history_content
        
        # Input field
        with Horizontal():
            self._input_widget = Input(
                placeholder="Type message or /command...",
                id="chat_input"
            )
            yield self._input_widget
        
        # Hint text
        yield Static("Commands: /add <path>  |  /switch <model_id>  |  /clear  |  Type to chat", classes="hint")

    def on_mount(self) -> None:
        """Mount panel and set up watchers."""
        # Watch active model changes
        self._unwatch_active_model = self._store.active_model.watch(
            lambda old, new: self._update_active_model_display(new)
        )
        self._update_active_model_display(self._store.active_model.value)

        # Add welcome message
        self._add_message("system", "Welcome! Chat with a loaded model or use /commands.")
        self._update_history_display()
        if self._input_widget:
            self._input_widget.focus()

    def on_unmount(self) -> None:
        """Clean up watchers."""
        if hasattr(self, "_unwatch_active_model"):
            self._unwatch_active_model()

    def _update_active_model_display(self, model_id: Optional[str]) -> None:
        """Update the active model label."""
        if not self._active_model_widget:
            return
        if model_id:
            self._active_model_widget.update(f"Model: {model_id}")
        else:
            self._active_model_widget.update("Model: none selected")

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
        if not self._history_content:
            return

        try:
            lines = []
            for role, message in self._chat_history[-50:]:  # Show last 50
                prefix = {
                    "user": "You: ",
                    "assistant": "Model: ",
                    "system": "ℹ️  ",
                    "error": "❌ ",
                }.get(role, "")
                lines.append(f"{prefix}{message}")

            self._history_content.update("\n".join(lines) if lines else "No messages yet.")

            if self._history_widget:
                # Two-pass scroll: immediate call reaches current layout bottom;
                # call_after_refresh reaches the new bottom after Textual
                # recalculates the Static widget's height.
                self._history_widget.scroll_end(animate=False)
                self.call_after_refresh(self._scroll_history_to_bottom)
        except Exception as e:
            logger.error(f"Error rendering chat history: {e}")

    def _scroll_history_to_bottom(self) -> None:
        """Scroll the chat history to the bottom after layout has updated."""
        if self._history_widget:
            self._history_widget.scroll_end(animate=False)

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
        
        if cmd == "/add":
            await self._cmd_add(arg)
        elif cmd == "/switch":
            await self._cmd_switch(arg)
        elif cmd == "/clear":
            self._chat_history.clear()
            self._add_message("system", "Chat history cleared.")
        elif cmd == "/help":
            self._add_message("system", "Commands: /add <path>, /switch <model_id>, /clear, /help")
        else:
            self._add_message("error", f"Unknown command: {cmd}")

    async def _cmd_add(self, path: str) -> None:
        """Handle /add command — import a local model file into LM Studio.

        Args:
            path: Local filesystem path to the model file to import.
        """
        if not path:
            self._add_message("error", "Usage: /add <local_path>")
            self._add_message("system", "Tip: press 'd' to browse and download models from Hugging Face")
            return

        cli = self._store.lms_cli
        if not cli:
            self._add_message("error", "lms CLI not found — cannot import model")
            return

        self._add_message("system", f"Importing: {path}…")
        try:
            import asyncio
            proc = await asyncio.create_subprocess_exec(
                str(cli.binary_path), "import", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
            if proc.returncode == 0:
                self._add_message("system", f"✓ Imported: {path}")
            else:
                err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
                self._add_message("error", f"Import failed: {err}")
        except Exception as e:
            logger.error(f"/add failed: {e}")
            self._add_message("error", f"Import failed: {e}")

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

    async def _run_stream(
        self,
        client,
        active_model: str,
        conversation: list[dict],
        assistant_index: int,
    ) -> None:
        """Execute the streaming chat completion loop.

        Runs as a cancellable asyncio.Task so that _cancel_current_stream()
        and _monitor_stream_health() can actually interrupt it.

        Args:
            client: LMStudioClient instance.
            active_model: Model ID to query.
            conversation: Message history to send.
            assistant_index: Index into _chat_history to update in-place.
        """
        full_response = ""
        async for chunk in client.chat_completion(active_model, conversation):
            self._last_chunk_time = time.time()
            full_response = full_response + chunk
            try:
                if 0 <= assistant_index < len(self._chat_history):
                    self._chat_history[assistant_index] = ("assistant", full_response)
                self._update_history_display()
            except Exception as e:
                logger.error(f"Error updating chat display during stream: {e}")
        logger.info(f"Chat response complete, length={len(full_response)}")

    async def _handle_chat(self, message: str) -> None:
        """Handle regular chat message with streaming response.

        Args:
            message: User's chat message.
        """
        # Cancel any existing stream
        if self._is_generating:
            self._cancel_current_stream()

        # Add user message to history
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

            # Build conversation history from chat history
            system_prompt = self._store.config.value.chat.system_prompt
            conversation = [{"role": "system", "content": system_prompt}] + [
                {"role": role, "content": content}
                for role, content in self._chat_history
                if role in ("user", "assistant")
            ]

            # Add placeholder for assistant response (updated in-place during stream)
            self._chat_history.append(("assistant", "⏳ Thinking..."))
            assistant_index = len(self._chat_history) - 1
            self._update_history_display()

            # Set generating state and start timeout monitor
            self._is_generating = True
            self._last_chunk_time = time.time()
            self._monitor_task = asyncio.create_task(self._monitor_stream_health())

            # Wrap stream in a task so _cancel_current_stream() can cancel it
            self._current_stream_task = asyncio.create_task(
                self._run_stream(client, active_model, conversation, assistant_index)
            )
            try:
                await self._current_stream_task
            except asyncio.CancelledError:
                logger.warning("Chat stream cancelled")
                self._chat_history[assistant_index] = (
                    "error",
                    "Response timed out or was cancelled. Try again with a shorter message.",
                )
                self._update_history_display()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            self._add_message("error", f"Chat failed: {e}")
        finally:
            self._is_generating = False
            self._current_stream_task = None
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
            self._monitor_task = None

    def _cancel_current_stream(self) -> None:
        """Cancel the current streaming request if one is active."""
        if self._current_stream_task and not self._current_stream_task.done():
            self._current_stream_task.cancel()
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._is_generating = False

    async def _monitor_stream_health(self) -> None:
        """Monitor for stalled streams and timeout if needed.
        
        Checks every 5 seconds to see if chunks have stopped arriving.
        If no chunks for _stream_timeout_seconds and GPU appears idle,
        cancels the stream task to prevent indefinite hanging.
        """
        try:
            while self._is_generating:
                await asyncio.sleep(5)  # Check every 5 seconds
                
                if not self._is_generating:
                    break
                
                time_since_chunk = time.time() - self._last_chunk_time
                if time_since_chunk > self._stream_timeout_seconds:
                    # Check GPU activity as secondary signal
                    gpu_busy = self._check_gpu_active()
                    
                    if not gpu_busy:
                        # Stream appears stalled - cancel it
                        logger.warning(
                            f"Stream timeout: No chunks for {time_since_chunk:.1f}s, GPU idle"
                        )
                        self._cancel_current_stream()
                        break
                    else:
                        # GPU is still working, extend timeout
                        logger.debug("GPU still active, extending timeout")
                        self._last_chunk_time = time.time()  # Reset timer
                        
        except asyncio.CancelledError:
            # Normal cancellation
            pass
        except Exception as e:
            logger.error(f"Stream monitor error: {e}")

    def _check_gpu_active(self) -> bool:
        """Check if any GPU has significant utilization (>10%).
        
        Returns:
            True if any GPU is busy, False otherwise.
        """
        try:
            from lmstudio_tui.gpu.monitor import GPUMetrics
            metrics = self._store.gpu_metrics.value
            return any(g.utilization > 10 for g in metrics)
        except Exception:
            # If we can't check, assume GPU might be busy to be safe
            return True
