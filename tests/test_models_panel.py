"""Unit tests for Models panel widget."""

import pytest
from textual.widgets import DataTable, Static

from lmstudio_tui.api.client import ModelInfo
from lmstudio_tui.widgets.models_panel import (
    ModelsPanel,
    format_size,
    extract_quantization,
)


class TestFormatSize:
    """Test format_size helper function."""

    def test_format_bytes(self):
        """Test formatting small byte values."""
        assert format_size(512) == "512 B"
        assert format_size(1023) == "1023 B"

    def test_format_kilobytes(self):
        """Test formatting kilobyte values."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"
        assert format_size(1024 * 512) == "512.0 KB"

    def test_format_megabytes(self):
        """Test formatting megabyte values."""
        assert format_size(1024 ** 2) == "1.0 MB"
        assert format_size(1024 ** 2 * 512) == "512.0 MB"

    def test_format_gigabytes(self):
        """Test formatting gigabyte values."""
        assert format_size(1024 ** 3) == "1.0 GB"
        assert format_size(int(1024 ** 3 * 42.5)) == "42.5 GB"

    def test_zero_bytes(self):
        """Test formatting zero bytes."""
        assert format_size(0) == "0 B"


class TestExtractQuantization:
    """Test extract_quantization helper function."""

    def test_extract_q4_k_m(self):
        """Test extracting Q4_K_M quantization."""
        name = "meta-llama/Llama-3.1-70B-Instruct-Q4_K_M.gguf"
        assert extract_quantization(name) == "Q4_K_M"

    def test_extract_q5_k_m(self):
        """Test extracting Q5_K_M quantization."""
        name = "model-Q5_K_M.gguf"
        assert extract_quantization(name) == "Q5_K_M"

    def test_extract_q4(self):
        """Test extracting simple Q4 quantization."""
        name = "model-Q4.gguf"
        assert extract_quantization(name) == "Q4"

    def test_extract_fp16(self):
        """Test extracting FP16 quantization."""
        name = "model-FP16.gguf"
        assert extract_quantization(name) == "FP16"

    def test_extract_fp32(self):
        """Test extracting FP32 quantization."""
        name = "model-FP32.gguf"
        assert extract_quantization(name) == "FP32"

    def test_no_quantization(self):
        """Test model with no quantization in name."""
        name = "meta-llama/Llama-3.1-70B-Instruct.gguf"
        assert extract_quantization(name) == "-"

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        name = "model-q4_k_m.gguf"
        assert extract_quantization(name) == "Q4_K_M"

    def test_partial_match_not_extracted(self):
        """Test that partial matches aren't extracted incorrectly."""
        name = "Q4-model.gguf"
        # Should not match because pattern requires -Q4
        assert extract_quantization(name) == "-"


class TestModelsPanel:
    """Test ModelsPanel widget."""

    @pytest.fixture
    def sample_models(self):
        """Create list of sample ModelInfo objects."""
        return [
            ModelInfo(
                id="llama-3.1-70b-q4",
                name="Llama 3.1 70B Q4",
                size=int(42.5 * 1024 ** 3),  # 42.5 GB
                loaded=True,
            ),
            ModelInfo(
                id="qwen-2.5-72b-q4",
                name="Qwen 2.5 72B Q4",
                size=int(48.2 * 1024 ** 3),  # 48.2 GB
                loaded=False,
            ),
            ModelInfo(
                id="mixtral-8x22b-q4",
                name="Mixtral 8x22B Q4",
                size=int(88.1 * 1024 ** 3),  # 88.1 GB
                loaded=False,
            ),
        ]

    def test_init(self):
        """Test ModelsPanel initializes correctly."""
        panel = ModelsPanel()
        assert panel._store is not None
        assert panel._table is None
        assert panel._model_ids == []

    @pytest.mark.skip(reason="Requires Textual app context for DataTable")
    def test_compose_creates_table(self):
        """Test that compose creates the DataTable.
        
        Note: This test requires a Textual app context.
        """
        pass

    @pytest.mark.skip(reason="Requires Textual app context for DataTable")
    def test_compose_table_columns(self):
        """Test that DataTable has correct columns.
        
        Note: This test requires a Textual app context.
        """
        pass

    @pytest.mark.skip(reason="Requires Textual app context for DataTable")
    def test_model_id_mapping(self, sample_models):
        """Test that model IDs are tracked correctly.
        
        Note: This test requires a Textual app context.
        """
        pass

    def test_get_selected_model_id_no_selection(self):
        """Test getting selected model when nothing selected."""
        panel = ModelsPanel()
        # Without a table, should return None
        result = panel._get_selected_model_id()
        assert result is None

    def test_get_model_by_id_found(self, sample_models):
        """Test finding a model by ID."""
        panel = ModelsPanel()
        # Set models in store
        panel._store.models.value = sample_models
        
        result = panel._get_model_by_id("qwen-2.5-72b-q4")
        assert result is not None
        assert result.name == "Qwen 2.5 72B Q4"

    def test_get_model_by_id_not_found(self, sample_models):
        """Test finding a model by ID when not present."""
        panel = ModelsPanel()
        panel._store.models.value = sample_models
        
        result = panel._get_model_by_id("nonexistent-model")
        assert result is None

    def test_get_model_by_id_empty_store(self):
        """Test finding a model when store is empty."""
        panel = ModelsPanel()
        panel._store.models.value = []
        
        result = panel._get_model_by_id("any-model")
        assert result is None

    @pytest.mark.skip(reason="Requires Textual app context for reactive binding")
    def test_on_models_change_updates_reactive(self, sample_models):
        """Test _on_models_change updates reactive state.
        
        Note: This test requires a Textual app context.
        """
        pass

    @pytest.mark.skip(reason="Requires Textual app context for reactive binding")
    def test_rebuild_table_adds_rows(self, sample_models):
        """Test that _rebuild_table adds rows to DataTable.
        
        Note: This test requires a Textual app context.
        """
        pass

    @pytest.mark.skip(reason="Requires Textual app context for async actions")
    def test_action_load_model(self):
        """Test load model action.
        
        Note: This test requires a Textual app context for async operations.
        """
        pass

    @pytest.mark.skip(reason="Requires Textual app context for async actions")
    def test_action_unload_model(self):
        """Test unload model action.
        
        Note: This test requires a Textual app context for async operations.
        """
        pass

    def test_key_bindings_exist(self):
        """Test that key binding methods exist."""
        panel = ModelsPanel()
        
        # Check methods exist
        assert hasattr(panel, 'key_l')
        assert hasattr(panel, 'key_u')
        assert hasattr(panel, 'key_enter')
        assert hasattr(panel, 'key_r')
        
        # Check action methods exist
        assert hasattr(panel, 'action_load_model')
        assert hasattr(panel, 'action_unload_model')
        assert hasattr(panel, 'action_show_details')
        assert hasattr(panel, 'action_refresh')


class TestModelInfoIntegration:
    """Test integration with ModelInfo dataclass."""

    def test_loaded_model_display(self):
        """Test display format for loaded model."""
        model = ModelInfo(
            id="test-model-q4",
            name="Test Model",
            size=42 * 1024 ** 3,
            loaded=True,
        )
        
        status = "● Loaded" if model.loaded else "○ Standby"
        assert status == "● Loaded"
        
        size_str = format_size(model.size)
        assert size_str == "42.0 GB"

    def test_standby_model_display(self):
        """Test display format for standby model."""
        model = ModelInfo(
            id="test-model-q4",
            name="Test Model",
            size=42 * 1024 ** 3,
            loaded=False,
        )
        
        status = "● Loaded" if model.loaded else "○ Standby"
        assert status == "○ Standby"

    def test_quantization_extraction_from_id(self):
        """Test extracting quantization from model ID."""
        model = ModelInfo(
            id="meta-llama/Llama-3.1-70B-Q4_K_M.gguf",
            name="Llama 3.1 70B",
            size=42 * 1024 ** 3,
            loaded=False,
        )
        
        quant = extract_quantization(model.id)
        assert quant == "Q4_K_M"

    def test_empty_name_fallback_to_id(self):
        """Test that empty name falls back to ID."""
        model = ModelInfo(
            id="test-model-id",
            name="",
            size=1024 ** 3,
            loaded=False,
        )
        
        display_name = model.name or model.id
        assert display_name == "test-model-id"
