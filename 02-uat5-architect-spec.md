# Architect Design Specification: UAT Session 5 Fixes

## Issues Overview

### Issue 1: Chat Fragility — Timeout & Error Handling
**Problem:** Chat locked up at "Thinking" stage with no recovery mechanism.

### Issue 2: GPU Header Row Not Rendering
**Problem:** Headers for GPU columns aren't appearing in the DataTable.

### Issue 3: Config Menu Layout Fix
**Problem:** Drop-down selectors have too much right-side spacing from config descriptions.

### Issue 5: VRAM/RAM Estimator Row
**Problem:** Users can't see memory impact of their config choices.

---

## Design Specifications

---

### Issue 1: Chat Timeout & Error Handling

#### Root Cause Analysis
The chat panel currently streams responses but has:
- No timeout detection for stalled responses
- No graceful handling of API failures during streaming
- No user feedback when the stream hangs

#### Solution Architecture

**A. Timeout Detection Based on GPU Activity**

```
Chat Request Flow:
1. User sends message → "Thinking..." appears
2. Start async stream from API
3. Start GPU activity monitor (parallel task)
4. For each chunk received:
   - Update display
   - Reset "last activity" timestamp
   - Check GPU utilization for "alive" signal
5. Timeout condition: No chunks AND GPU idle > 30s
6. On timeout: Cancel stream, show error, allow retry
```

**B. Implementation Plan**

**File:** `chat_panel.py`

Add state tracking:
```python
# New reactive states
_is_generating: reactive[bool] = reactive(False)
_last_chunk_time: reactive[float] = reactive(0.0)
_stream_timeout_seconds: float = 30.0  # Configurable
```

**Timeout Logic:**
```python
async def _monitor_stream_health(self) -> None:
    """Monitor for stalled streams and timeout if needed."""
    while self._is_generating:
        await asyncio.sleep(5)  # Check every 5 seconds
        
        time_since_chunk = time.time() - self._last_chunk_time
        if time_since_chunk > self._stream_timeout_seconds:
            # Check GPU activity as secondary signal
            gpu_busy = await self._check_gpu_active()
            
            if not gpu_busy:
                # Stream appears stalled
                self._cancel_stream("Response timeout - stream stalled")
                return

async def _check_gpu_active(self) -> bool:
    """Check if any GPU has significant utilization."""
    metrics = self._store.gpu_metrics.value
    return any(g.utilization > 10 for g in metrics)
```

**Error Recovery UI:**
- Show error message in chat history (red, prefixed with ❌)
- Add "Retry" button below error (or auto-clear on new message)
- Reset `_is_generating` state to allow new messages

**C. Interface Changes**

```python
# chat_panel.py - New methods
async def _handle_chat(self, message: str) -> None:
    # ... existing setup ...
    
    self._is_generating = True
    self._last_chunk_time = time.time()
    
    # Start monitor task
    monitor_task = asyncio.create_task(self._monitor_stream_health())
    
    try:
        async for chunk in client.chat_completion(...):
            self._last_chunk_time = time.time()
            # ... update display ...
    except asyncio.CancelledError:
        self._add_message("error", "Request cancelled (timeout)")
    except Exception as e:
        self._add_message("error", f"Chat failed: {e}")
    finally:
        self._is_generating = False
        monitor_task.cancel()
```

---

### Issue 2: GPU Header Row Rendering

#### Root Cause Analysis
Looking at `gpu_panel.py`:
- `DataTable` is created with `show_header=True`
- Columns are added in `on_mount()` via `_setup_data_table()`
- BUT: `compose()` runs BEFORE `on_mount()`, so at render time the DataTable has no columns defined

#### Solution Architecture

**The Fix: Move column setup to compose() or use watch callback properly**

Two approaches:

**Approach A (Recommended):** Ensure DataTable is fully initialized before first render

Current issue in `GPUPanel.compose()`:
```python
def compose(self):
    yield Static("🎮 GPU STATUS", classes="title")
    self._data_table = DataTable(show_header=True, header_height=1)
    yield self._data_table  # ← No columns yet! Header won't render
```

Fix: Set up columns immediately after creation or in `on_mount()` before data arrives:

```python
def on_mount(self) -> None:
    """Mount panel and set up store watchers."""
    # Watch for GPU metrics changes
    self._unwatch_metrics = self._store.gpu_metrics.watch(self._on_metrics_change)
    self._unwatch_error = self._store.gpu_error.watch(self._on_error_change)

    # CRITICAL: Initialize DataTable columns BEFORE any data arrives
    if self._data_table:
        self._setup_data_table()
        self._data_table.show_header = True  # Ensure header is visible
        self._data_table.refresh()  # Force refresh to render header

    # Initial render if data already available
    initial_metrics = self._store.gpu_metrics.value
    if initial_metrics:
        self._gpu_metrics = initial_metrics
```

**Alternative Approach B:** Add columns in `compose()` using a helper

```python
def compose(self):
    yield Static("🎮 GPU STATUS", classes="title")
    table = DataTable(show_header=True, header_height=1)
    # Add columns immediately
    table.add_column("GPU", width=25)
    table.add_column("Model", width=20)
    # ... etc
    self._data_table = table
    yield table
```

**Recommended: Approach A** - minimal change, keeps current architecture

---

### Issue 3: Config Menu Layout Fix

#### Root Cause Analysis
Current layout in `models_panel.py`:
```python
with Horizontal():
    yield Static("GPU Offload:", classes="config-label")
    self._offload_select = Select(OFFLOAD_OPTIONS, value=-1, id="offload_select")
    yield self._offload_select
```

Problems:
1. Horizontal layout puts label and selector side-by-side with fixed widths
2. `config-label` has `width: 20` creating spacing gap
3. Selectors appear far from their descriptions

#### Solution Architecture

**New Layout: Vertical Stack**

```
OLD (Horizontal):
┌─────────────────────────────────────┐
│ GPU Offload:     [Max ▼]            │  ← Too much space
│ Context:         [8K ▼]             │
│ KV Cache:        [F16 ▼]            │
└─────────────────────────────────────┘

NEW (Vertical - compact):
┌─────────────────────────────────────┐
│ GPU Offload                         │
│ [Max ▼]                             │  ← Selector directly under
│                                     │
│ Context Length                      │
│ [8K ▼]                              │
│                                     │
│ KV Cache Quantization               │
│ [F16 (best quality) ▼]              │
└─────────────────────────────────────┘
```

**CSS Changes:**
```css
/* Remove fixed width from label, stack vertically */
ModelsPanel Static.config-label {
    color: $text;
    text-style: bold;
    height: 1;
    width: 100%;  /* Full width, not fixed */
}

ModelsPanel Select {
    width: 100%;  /* Full width */
    margin-top: 0;
    margin-bottom: 1;  /* Space between configs */
}

/* New description text styling */
ModelsPanel Static.config-desc {
    color: $text-muted;
    height: 1;
    width: 100%;
    text-style: italic;
}
```

**Compose Changes:**
```python
# GPU Offload
yield Static("GPU Offload", classes="config-label")
yield Static("Percentage of model layers on GPU", classes="config-desc")
self._offload_select = Select(OFFLOAD_OPTIONS, value=-1, id="offload_select")
yield self._offload_select

# Context Length  
yield Static("Context Length", classes="config-label")
yield Static("Token window for conversation", classes="config-desc")
self._context_select = Select(CONTEXT_OPTIONS, value=8192, id="context_select")
yield self._context_select

# KV Cache Quantization
yield Static("KV Cache Quantization", classes="config-label")
yield Static("Memory precision for attention cache", classes="config-desc")
self._kv_quant_select = Select(KV_QUANT_OPTIONS, value="f16", id="kv_quant_select")
yield self._kv_quant_select
```

---

### Issue 5: VRAM/RAM Estimator Row

#### Root Cause Analysis
Users need visibility into memory impact before loading. Current config shows settings but not their combined memory effect.

#### Solution Architecture

**Memory Calculation Formula**

Based on llama.cpp/LM Studio behavior:

```python
def estimate_memory_usage(
    model_size_bytes: int,
    context_length: int,
    gpu_offload_percent: int,
    kv_cache_quantization: str,
    quantization_bits: float = 16.0,  # From model quant info
) -> tuple[float, float]:
    """Estimate VRAM and RAM usage for a model load configuration.
    
    Returns:
        (estimated_vram_gb, estimated_ram_gb)
    """
    # Model weights memory (depends on quantization)
    model_weights_gb = model_size_bytes / (1024 ** 3)
    
    # KV cache calculation: 2 * num_layers * num_kv_heads * head_dim * context * bytes_per_token
    # Simplified approximation: ~2 bytes per token per billion params for F16
    # Q8_0 = 1 byte, Q4_0 = 0.5 bytes
    kv_bytes_per_token = {
        "f16": 2.0,
        "q8_0": 1.0, 
        "q4_0": 0.5,
    }.get(kv_cache_quantization, 2.0)
    
    # Approximate KV cache size (simplified model)
    # Typical: 2 * context_length * kv_bytes_per_token * (model_size_factor)
    # Model size factor: larger models have more attention heads
    model_size_factor = max(1.0, model_weights_gb / 10)  # Scale with model size
    kv_cache_gb = (2 * context_length * kv_bytes_per_token * model_size_factor) / (1024 ** 3)
    
    # Total working memory
    total_memory_gb = model_weights_gb + kv_cache_gb + 0.5  # +0.5GB overhead
    
    # Split by GPU offload
    if gpu_offload_percent < 0:  # Max
        # All layers on GPU if possible
        gpu_layers = 100  # Assume max
    else:
        gpu_layers = gpu_offload_percent
    
    # Simplified: offload percentage maps directly to memory split
    # (In reality it's layer-based, but this is a good estimate)
    vram_ratio = gpu_layers / 100.0
    
    estimated_vram = total_memory_gb * vram_ratio
    estimated_ram = total_memory_gb * (1 - vram_ratio)
    
    return (estimated_vram, estimated_ram)
```

**UI Integration**

Add to `models_panel.py`:
```python
# New widget references
self._vram_estimate_widget: Static | None = None

def compose(self):
    # ... existing widgets ...
    
    # Memory estimator row
    yield Static("💾 MEMORY ESTIMATE", classes="config-title")
    self._vram_estimate_widget = Static("Select a model to see estimate", classes="vram-estimate")
    yield self._vram_estimate_widget

# Update estimate when config changes
def _update_memory_estimate(self) -> None:
    """Update the VRAM/RAM estimate display."""
    if not self._vram_estimate_widget:
        return
    
    model_id = self._get_selected_model_id()
    if not model_id:
        self._vram_estimate_widget.update("Select a model to see estimate")
        return
    
    # Get model info
    model = self._get_model_by_id(model_id)
    if not model:
        return
    
    # Get current config
    config = self._store.get_model_config(model_id)
    
    # Calculate
    vram_gb, ram_gb = self._calculate_estimate(model, config)
    
    # Get available VRAM
    total_vram = sum(g.vram_total for g in self._store.gpu_metrics.value) / 1024
    available_vram = total_vram - sum(g.vram_used for g in self._store.gpu_metrics.value) / 1024
    
    # Format display
    status_color = "green" if vram_gb < available_vram * 0.9 else "yellow" if vram_gb < available_vram else "red"
    
    estimate_text = f"VRAM: {vram_gb:.1f}GB / Available: {available_vram:.1f}GB | RAM: {ram_gb:.1f}GB"
    self._vram_estimate_widget.update(estimate_text)
    
    # Update color class
    self._vram_estimate_widget.remove_class("green", "yellow", "red")
    self._vram_estimate_widget.add_class(status_color)
```

**CSS for Estimator:**
```css
ModelsPanel Static.vram-estimate {
    height: 1;
    width: 100%;
    content-align: center middle;
    text-style: bold;
}
ModelsPanel Static.vram-estimate.green {
    color: $success;
}
ModelsPanel Static.vram-estimate.yellow {
    color: $warning;
}
ModelsPanel Static.vram-estimate.red {
    color: $error;
}
```

---

## Summary of Changes by File

### chat_panel.py
1. Add `_is_generating` and `_last_chunk_time` reactive states
2. Add `_stream_timeout_seconds` constant
3. Add `_monitor_stream_health()` async method
4. Add `_check_gpu_active()` helper
5. Modify `_handle_chat()` to start monitor task and handle cancellation

### gpu_panel.py
1. In `on_mount()`, ensure `_setup_data_table()` is called before data arrives
2. Add explicit `show_header = True` and `refresh()` call

### models_panel.py
1. Change config layout from Horizontal to Vertical
2. Add `config-desc` CSS class for descriptions
3. Add `_vram_estimate_widget` reference
4. Add `_calculate_estimate()` method with memory formula
5. Add `_update_memory_estimate()` method
6. Call `_update_memory_estimate()` on selection/config changes
7. Add VRAM estimate row to compose()

---

## Testing Strategy

1. **Chat Timeout:** 
   - Mock slow stream, verify timeout triggers
   - Verify error message appears and retry works
   
2. **GPU Headers:**
   - Launch app, verify "GPU", "Model", "VRAM Total" headers visible
   - Test with 1-4 GPUs
   
3. **Config Layout:**
   - Verify selectors are directly under labels
   - Check compact spacing
   
4. **VRAM Estimator:**
   - Select different models, verify estimates change
   - Adjust context/offload, verify estimates update
   - Compare with actual LM Studio behavior

---

## Success Criteria

1. ✅ Chat shows error after 30s of stalled response
2. ✅ GPU DataTable headers render correctly
3. ✅ Config selectors are compact and under labels
4. ✅ VRAM estimate shows meaningful values that update with config changes
5. ✅ All existing tests pass
6. ✅ Version bumped to 0.1.9-uat11

---

**Next Step:** Builder implements these specifications.
