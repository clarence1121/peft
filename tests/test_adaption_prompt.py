# Copyright 2023-present the HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import importlib
import os
import tempfile
import unittest
from unittest import TestCase

import pytest
import torch
from torch.testing import assert_close

from peft.mapping import get_peft_model
from peft.peft_model import PeftModel
from peft.tuners.adaption_prompt import AdaptionPromptConfig
from peft.utils.other import prepare_model_for_kbit_training
from peft.utils.save_and_load import get_peft_model_state_dict
from tests.testing_common import PeftCommonTester


def is_llama_available() -> bool:
    """Check if Llama is available in the transformers library (it's not in earlier versions)."""
    try:
        return importlib.util.find_spec("transformers.models.llama.modeling_llama") is not None
    except ModuleNotFoundError:
        return False


def is_mistral_available() -> bool:
    """Check if mistral is available in the transformers library (it's not in earlier versions)."""
    try:
        return importlib.util.find_spec("transformers.models.mistral.modeling_mistral") is not None
    except ModuleNotFoundError:
        return False


if is_llama_available():
    # We guard the import statement so that our unit tests will pass in CI environments
    # that don't have a transformers package with Llama.
    from transformers import LlamaConfig, LlamaForCausalLM, LlamaModel

if is_mistral_available():
    # We guard the import statement so that our unit tests will pass in CI environments
    # that don't have a transformers package with Mistral.
    from transformers import MistralConfig, MistralForCausalLM, MistralModel


class AdaptionPromptTester(TestCase, PeftCommonTester):
    """
    Tests for the AdaptionPrompt model.

    Some of these tests were adapted from `test_peft_model.py` (which has been refactored since), but since we haven't
    checked in the test checkpoints for Llama into `hf-internal-testing`, we separate them for now.
    """

    def setUp(self):
        # Check that llama is available in transformers package before running each test.
        if not is_llama_available():
            self.skipTest("Llama not available in transformers. Skipping all tests.")
        else:
            # Check for Mistral's availability. It might or might not be available.
            self.mistral_available = is_mistral_available()

    @staticmethod
    def _create_test_llama_config():
        """Create a test config for a small Llama model for testing."""
        return LlamaConfig(
            vocab_size=16,
            hidden_size=8,
            intermediate_size=8,
            num_hidden_layers=8,
            num_attention_heads=4,
            use_cache=False,
        )

    @staticmethod
    def _create_test_mistral_config():
        """Create a test config for a small Mistral model for testing."""
        return MistralConfig(
            vocab_size=16,
            hidden_size=8,
            intermediate_size=8,
            num_hidden_layers=8,
            num_attention_heads=4,
            num_key_value_heads=2,
            use_cache=False,
        )

    def test_attributes(self) -> None:
        model = LlamaModel(self._create_test_llama_config())
        config = AdaptionPromptConfig(adapter_layers=1, adapter_len=4)
        model = get_peft_model(model, config)

        assert hasattr(model, "save_pretrained")
        assert hasattr(model, "from_pretrained")
        assert hasattr(model, "push_to_hub")

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_attributes_mistral(self) -> None:
        model_mistral = MistralModel(self._create_test_mistral_config())
        config_mistral = AdaptionPromptConfig(adapter_layers=1, adapter_len=4)
        model_mistral = get_peft_model(model_mistral, config_mistral)

        assert hasattr(model_mistral, "save_pretrained")
        assert hasattr(model_mistral, "from_pretrained")
        assert hasattr(model_mistral, "push_to_hub")

    def test_prepare_for_training(self) -> None:
        # Test Llama
        model = LlamaForCausalLM(self._create_test_llama_config())
        config = AdaptionPromptConfig(adapter_layers=1, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        model = model.to(self.torch_device)

        dummy_input = torch.LongTensor([[1, 1, 1]]).to(self.torch_device)
        dummy_output = model.get_input_embeddings()(dummy_input)

        assert not dummy_output.requires_grad

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_prepare_for_training_mistral(self) -> None:
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        config_mistral = AdaptionPromptConfig(adapter_layers=1, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral = get_peft_model(model_mistral, config_mistral)
        model_mistral = model_mistral.to(self.torch_device)

        dummy_input = torch.LongTensor([[1, 1, 1]]).to(self.torch_device)
        dummy_output = model_mistral.get_input_embeddings()(dummy_input)

        assert not dummy_output.requires_grad

    def test_prepare_for_int8_training(self) -> None:
        model = LlamaForCausalLM(self._create_test_llama_config())
        model = prepare_model_for_kbit_training(model)
        model = model.to(self.torch_device)

        for param in model.parameters():
            assert not param.requires_grad

        config = AdaptionPromptConfig(adapter_layers=1, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config)

        # For backward compatibility
        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()
        else:

            def make_inputs_require_grad(module, input, output):
                output.requires_grad_(True)

            model.get_input_embeddings().register_forward_hook(make_inputs_require_grad)

        dummy_input = torch.LongTensor([[1, 1, 1]]).to(self.torch_device)
        dummy_output = model.get_input_embeddings()(dummy_input)

        assert dummy_output.requires_grad

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_prepare_model_for_kbit_training_mistral(self) -> None:
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        model_mistral = prepare_model_for_kbit_training(model_mistral)
        model_mistral = model_mistral.to(self.torch_device)

        for param in model_mistral.parameters():
            assert not param.requires_grad

        config_mistral = AdaptionPromptConfig(adapter_layers=1, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral = get_peft_model(model_mistral, config_mistral)

        # For backward compatibility
        if hasattr(model_mistral, "enable_input_require_grads"):
            model_mistral.enable_input_require_grads()
        else:

            def make_inputs_require_grad(module, input, output):
                output.requires_grad_(True)

            model_mistral.get_input_embeddings().register_forward_hook(make_inputs_require_grad)

        dummy_input = torch.LongTensor([[1, 1, 1]]).to(self.torch_device)
        dummy_output = model_mistral.get_input_embeddings()(dummy_input)

        assert dummy_output.requires_grad

    def test_save_pretrained_regression(self) -> None:
        seed = 420
        torch.manual_seed(seed)
        model = LlamaForCausalLM(self._create_test_llama_config())
        config = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        model = model.to(self.torch_device)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname, safe_serialization=False)

            torch.manual_seed(seed)
            model_from_pretrained = LlamaForCausalLM(self._create_test_llama_config())
            model_from_pretrained = PeftModel.from_pretrained(model_from_pretrained, tmp_dirname)

            # check if the state dicts are equal
            state_dict = get_peft_model_state_dict(model)
            state_dict_from_pretrained = get_peft_model_state_dict(model_from_pretrained)

            # check if same keys
            assert state_dict.keys() == state_dict_from_pretrained.keys()

            # Check that the number of saved parameters is 4 -- 2 layers of (tokens and gate).
            assert len(state_dict) == 4

            # check if tensors equal
            for key in state_dict.keys():
                assert torch.allclose(
                    state_dict[key].to(self.torch_device), state_dict_from_pretrained[key].to(self.torch_device)
                )

            # check if `adapter_model.bin` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_model.bin"))

            # check if `adapter_config.json` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_config.json"))

            # check if `model.safetensors` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "model.safetensors"))

            # check if `config.json` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "config.json"))

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_save_pretrained_regression_mistral(self) -> None:
        seed = 420
        torch.manual_seed(seed)
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        config_mistral = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral = get_peft_model(model_mistral, config_mistral)
        model_mistral = model_mistral.to(self.torch_device)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model_mistral.save_pretrained(tmp_dirname, safe_serialization=False)

            torch.manual_seed(seed)
            model_from_pretrained_mistral = MistralForCausalLM(self._create_test_mistral_config())
            model_from_pretrained_mistral = PeftModel.from_pretrained(model_from_pretrained_mistral, tmp_dirname)

            # check if the state dicts are equal
            state_dict = get_peft_model_state_dict(model_mistral)
            state_dict_from_pretrained = get_peft_model_state_dict(model_from_pretrained_mistral)

            # check if same keys
            assert state_dict.keys() == state_dict_from_pretrained.keys()

            # Check that the number of saved parameters is 4 -- 2 layers of (tokens and gate).
            assert len(state_dict) == 4

            # check if tensors equal
            for key in state_dict.keys():
                assert torch.allclose(
                    state_dict[key].to(self.torch_device), state_dict_from_pretrained[key].to(self.torch_device)
                )

            # check if `adapter_model.bin` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_model.bin"))

            # check if `adapter_config.json` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_config.json"))

            # check if `model.safetensors` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "model.safetensors"))

            # check if `config.json` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "config.json"))

    def test_save_pretrained(self) -> None:
        seed = 420
        torch.manual_seed(seed)
        model = LlamaForCausalLM(self._create_test_llama_config())
        config = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        model = model.to(self.torch_device)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            torch.manual_seed(seed)
            model_from_pretrained = LlamaForCausalLM(self._create_test_llama_config())
            model_from_pretrained = PeftModel.from_pretrained(model_from_pretrained, tmp_dirname)

            # check if the state dicts are equal
            state_dict = get_peft_model_state_dict(model)
            state_dict_from_pretrained = get_peft_model_state_dict(model_from_pretrained)

            # check if same keys
            assert state_dict.keys() == state_dict_from_pretrained.keys()

            # Check that the number of saved parameters is 4 -- 2 layers of (tokens and gate).
            assert len(state_dict) == 4

            # check if tensors equal
            for key in state_dict.keys():
                assert torch.allclose(
                    state_dict[key].to(self.torch_device), state_dict_from_pretrained[key].to(self.torch_device)
                )

            # check if `adapter_model.bin` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_model.safetensors"))

            # check if `adapter_config.json` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_config.json"))

            # check if `model.safetensors` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "model.safetensors"))

            # check if `config.json` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "config.json"))

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_save_pretrained_mistral(self) -> None:
        seed = 420
        torch.manual_seed(seed)
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        config_mistral = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral = get_peft_model(model_mistral, config_mistral)
        model_mistral = model_mistral.to(self.torch_device)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model_mistral.save_pretrained(tmp_dirname)

            torch.manual_seed(seed)
            model_from_pretrained_mistral = MistralForCausalLM(self._create_test_mistral_config())
            model_from_pretrained_mistral = PeftModel.from_pretrained(model_from_pretrained_mistral, tmp_dirname)

            # check if the state dicts are equal
            state_dict = get_peft_model_state_dict(model_mistral)
            state_dict_from_pretrained = get_peft_model_state_dict(model_from_pretrained_mistral)

            # check if same keys
            assert state_dict.keys() == state_dict_from_pretrained.keys()

            # Check that the number of saved parameters is 4 -- 2 layers of (tokens and gate).
            assert len(state_dict) == 4

            # check if tensors equal
            for key in state_dict.keys():
                assert torch.allclose(
                    state_dict[key].to(self.torch_device), state_dict_from_pretrained[key].to(self.torch_device)
                )

            # check if `adapter_model.bin` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_model.safetensors"))

            # check if `adapter_config.json` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_config.json"))

            # check if `model.safetensors` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "model.safetensors"))

            # check if `config.json` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "config.json"))

    def test_save_pretrained_selected_adapters(self) -> None:
        seed = 420
        torch.manual_seed(seed)
        model = LlamaForCausalLM(self._create_test_llama_config())
        config = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        model = model.to(self.torch_device)

        new_adapter_config = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model.add_adapter("new_adapter", new_adapter_config)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            torch.manual_seed(seed)
            model_from_pretrained = LlamaForCausalLM(self._create_test_llama_config())
            model_from_pretrained = PeftModel.from_pretrained(model_from_pretrained, tmp_dirname)

            model_from_pretrained.load_adapter(tmp_dirname, "new_adapter")

            # check if the state dicts are equal
            state_dict = get_peft_model_state_dict(model)
            state_dict_from_pretrained = get_peft_model_state_dict(model_from_pretrained)

            # check if same keys
            assert state_dict.keys() == state_dict_from_pretrained.keys()

            # Check that the number of saved parameters is 4 -- 2 layers of (tokens and gate).
            assert len(state_dict) == 4

            # check if tensors equal
            for key in state_dict.keys():
                assert torch.allclose(
                    state_dict[key].to(self.torch_device), state_dict_from_pretrained[key].to(self.torch_device)
                )

            # check if `adapter_model.bin` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_model.safetensors"))

            # check if `adapter_config.json` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_config.json"))

            # check if `model.safetensors` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "model.safetensors"))

            # check if `config.json` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "config.json"))

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_save_pretrained_selected_adapters_mistral(self) -> None:
        seed = 420
        torch.manual_seed(seed)
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        config_mistral = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral = get_peft_model(model_mistral, config_mistral)
        model_mistral = model_mistral.to(self.torch_device)

        new_adapter_config_mistral = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral.add_adapter("new_adapter", new_adapter_config_mistral)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model_mistral.save_pretrained(tmp_dirname)

            torch.manual_seed(seed)
            model_from_pretrained_mistral = MistralForCausalLM(self._create_test_mistral_config())
            model_from_pretrained_mistral = PeftModel.from_pretrained(model_from_pretrained_mistral, tmp_dirname)

            model_from_pretrained_mistral.load_adapter(tmp_dirname, "new_adapter")

            # check if the state dicts are equal
            state_dict = get_peft_model_state_dict(model_mistral)
            state_dict_from_pretrained = get_peft_model_state_dict(model_from_pretrained_mistral)

            # check if same keys
            assert state_dict.keys() == state_dict_from_pretrained.keys()

            # Check that the number of saved parameters is 4 -- 2 layers of (tokens and gate).
            assert len(state_dict) == 4

            # check if tensors equal
            for key in state_dict.keys():
                assert torch.allclose(
                    state_dict[key].to(self.torch_device), state_dict_from_pretrained[key].to(self.torch_device)
                )

            # check if `adapter_model.bin` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_model.safetensors"))

            # check if `adapter_config.json` is present
            assert os.path.exists(os.path.join(tmp_dirname, "adapter_config.json"))

            # check if `model.safetensors` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "model.safetensors"))

            # check if `config.json` is not present
            assert not os.path.exists(os.path.join(tmp_dirname, "config.json"))

    def test_generate(self) -> None:
        model = LlamaForCausalLM(self._create_test_llama_config())
        config = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        model = model.to(self.torch_device)

        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        attention_mask = torch.LongTensor([[1, 1, 1], [1, 0, 1]]).to(self.torch_device)

        # check if `generate` works
        _ = model.generate(input_ids=input_ids, attention_mask=attention_mask)

        # check if `generate` works if positional arguments are passed
        _ = model.generate(input_ids, attention_mask=attention_mask)

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_generate_mistral(self) -> None:
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        config_mistral = AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        model_mistral = get_peft_model(model_mistral, config_mistral)
        model_mistral = model_mistral.to(self.torch_device)

        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        attention_mask = torch.LongTensor([[1, 1, 1], [1, 0, 1]]).to(self.torch_device)

        # check if `generate` works
        _ = model_mistral.generate(input_ids=input_ids, attention_mask=attention_mask)

        # check if `generate` works if positional arguments are passed
        _ = model_mistral.generate(input_ids, attention_mask=attention_mask)

    def test_sequence_adapter_ops(self) -> None:
        """Test sequence of adapter operations."""
        # Test input data.
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        target_ids = torch.LongTensor([[0, 0, 0], [0, 0, 0]]).to(self.torch_device)
        attention_mask = torch.LongTensor([[1, 1, 1], [1, 0, 1]]).to(self.torch_device)

        # Create original llama model.
        original = LlamaForCausalLM(self._create_test_llama_config())
        original = original.to(self.torch_device)
        original_before = original(input_ids=input_ids, attention_mask=attention_mask)

        # Get AdaptionPrompt model.
        adapted = get_peft_model(
            original, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted = adapted.to(self.torch_device)
        default_before = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)

        # Test zero-init: The logits should be exactly the same.
        assert_close(original_before.logits, default_before.logits, rtol=0, atol=0)

        # Single fine-tuning step on "default" adapter.
        optimizer = torch.optim.SGD(adapted.parameters(), lr=1)
        optimizer.zero_grad()
        default_before.loss.backward()
        optimizer.step()

        # Test that the output changed.
        default_after = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert not torch.allclose(default_before.logits, default_after.logits)

        with adapted.disable_adapter():
            # Test that the output is the same as the original output.
            default_disabled = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
            assert_close(original_before.logits, default_disabled.logits, rtol=0, atol=0)

        # Add new adapter 1.
        adapted.add_adapter("adapter 1", AdaptionPromptConfig(adapter_layers=3, adapter_len=8, task_type="CAUSAL_LM"))
        # Test zero-init
        adapter_1_before = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(original_before.logits, adapter_1_before.logits, rtol=0, atol=0)

        # Single fine-tuning step on adapter 1.
        optimizer = torch.optim.SGD(adapted.parameters(), lr=1)
        optimizer.zero_grad()
        adapter_1_before.loss.backward()
        optimizer.step()

        # Test that adapter 1 output changed.
        adapter_1_after = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert not torch.allclose(adapter_1_before.logits, adapter_1_after.logits)
        assert not torch.allclose(original_before.logits, adapter_1_after.logits)
        assert not torch.allclose(default_after.logits, adapter_1_after.logits)

        with adapted.disable_adapter():
            # Test that the output is the same as the original output.
            adapter_1_disabled = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
            assert_close(original_before.logits, adapter_1_disabled.logits, rtol=0, atol=0)

        # Set adapter back to default.
        adapted.set_adapter("default")

        # Test that the output is the same as the default output after training.
        default_after_set = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(default_after.logits, default_after_set.logits, rtol=0, atol=0)
        assert not torch.allclose(original_before.logits, default_after_set.logits)
        assert not torch.allclose(adapter_1_after.logits, default_after_set.logits)

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_sequence_adapter_ops_mistral(self) -> None:
        # Test input data.
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        target_ids = torch.LongTensor([[0, 0, 0], [0, 0, 0]]).to(self.torch_device)
        attention_mask = torch.LongTensor([[1, 1, 1], [1, 0, 1]]).to(self.torch_device)

        # Create original mistral model.
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        model_mistral = model_mistral.to(self.torch_device)
        original_before = model_mistral(input_ids=input_ids, attention_mask=attention_mask)

        # Get AdaptionPrompt model.
        adapted_mistral = get_peft_model(
            model_mistral, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted_mistral = adapted_mistral.to(self.torch_device)
        default_before = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)

        # Test zero-init: The logits should be exactly the same.
        assert_close(original_before.logits, default_before.logits, rtol=0, atol=0)

        # Single fine-tuning step on "default" adapter.
        optimizer = torch.optim.SGD(adapted_mistral.parameters(), lr=1)
        optimizer.zero_grad()
        default_before.loss.backward()
        optimizer.step()

        # Test that the output changed.
        default_after = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert not torch.allclose(default_before.logits, default_after.logits)

        with adapted_mistral.disable_adapter():
            # Test that the output is the same as the original output.
            default_disabled = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
            assert_close(original_before.logits, default_disabled.logits, rtol=0, atol=0)

        # Add new adapter 1.
        adapted_mistral.add_adapter(
            "adapter 1", AdaptionPromptConfig(adapter_layers=3, adapter_len=8, task_type="CAUSAL_LM")
        )
        # Test zero-init
        adapter_1_before = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(original_before.logits, adapter_1_before.logits, rtol=0, atol=0)

        # Single fine-tuning step on adapter 1.
        optimizer = torch.optim.SGD(adapted_mistral.parameters(), lr=1)
        optimizer.zero_grad()
        adapter_1_before.loss.backward()
        optimizer.step()

        # Test that adapter 1 output changed.
        adapter_1_after = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert not torch.allclose(adapter_1_before.logits, adapter_1_after.logits)
        assert not torch.allclose(original_before.logits, adapter_1_after.logits)
        assert not torch.allclose(default_after.logits, adapter_1_after.logits)

        with adapted_mistral.disable_adapter():
            # Test that the output is the same as the original output.
            adapter_1_disabled = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
            assert_close(original_before.logits, adapter_1_disabled.logits, rtol=0, atol=0)

        # Set adapter back to default.
        adapted_mistral.set_adapter("default")

        # Test that the output is the same as the default output after training.
        default_after_set = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(default_after.logits, default_after_set.logits, rtol=0, atol=0)
        assert not torch.allclose(original_before.logits, default_after_set.logits)
        assert not torch.allclose(adapter_1_after.logits, default_after_set.logits)

    def test_add_and_set_while_disabled(self):
        """Test that adding and setting adapters while disabled works as intended."""
        # Test input data.
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        target_ids = torch.LongTensor([[0, 0, 0], [0, 0, 0]]).to(self.torch_device)
        attention_mask = torch.LongTensor([[1, 1, 1], [1, 0, 1]]).to(self.torch_device)

        # Create original llama model.
        original = LlamaForCausalLM(self._create_test_llama_config())
        original = original.to(self.torch_device)
        original_before = original(input_ids=input_ids, attention_mask=attention_mask)

        # Get AdaptionPrompt model.
        adapted = get_peft_model(
            original, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted = adapted.to(self.torch_device)

        with adapted.disable_adapter():
            adapted.add_adapter(
                "adapter 1", AdaptionPromptConfig(adapter_layers=3, adapter_len=8, task_type="CAUSAL_LM")
            )

        # Test that the output is the same as the original output.
        adapter_1_before = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(original_before.logits, adapter_1_before.logits, rtol=0, atol=0)

        # Single fine-tuning step on adapter 1.
        optimizer = torch.optim.SGD(adapted.parameters(), lr=1)
        optimizer.zero_grad()
        adapter_1_before.loss.backward()
        optimizer.step()

        # Test that adapter 1 output changed.
        adapter_1_after = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert not torch.allclose(original_before.logits, adapter_1_after.logits)

        adapted.set_adapter("default")
        with adapted.disable_adapter():
            adapted.set_adapter("adapter 1")

        # Test that adapter 1 is active again.
        adapter_1_after_set = adapted(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(adapter_1_after.logits, adapter_1_after_set.logits, rtol=0, atol=0)

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_add_and_set_while_disabled_mistral(self):
        # Test input data.
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        target_ids = torch.LongTensor([[0, 0, 0], [0, 0, 0]]).to(self.torch_device)
        attention_mask = torch.LongTensor([[1, 1, 1], [1, 0, 1]]).to(self.torch_device)

        # Create original mistral model.
        model_mistral = MistralForCausalLM(self._create_test_mistral_config())
        model_mistral = model_mistral.to(self.torch_device)
        original_before = model_mistral(input_ids=input_ids, attention_mask=attention_mask)

        # Get AdaptionPrompt model.
        adapted_mistral = get_peft_model(
            model_mistral, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted_mistral = adapted_mistral.to(self.torch_device)

        with adapted_mistral.disable_adapter():
            adapted_mistral.add_adapter(
                "adapter 1", AdaptionPromptConfig(adapter_layers=3, adapter_len=8, task_type="CAUSAL_LM")
            )

        # Test that the output is the same as the original output.
        adapter_1_before = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(original_before.logits, adapter_1_before.logits, rtol=0, atol=0)

        # Single fine-tuning step on adapter 1.
        optimizer = torch.optim.SGD(adapted_mistral.parameters(), lr=1)
        optimizer.zero_grad()
        adapter_1_before.loss.backward()
        optimizer.step()

        # Test that adapter 1 output changed.
        adapter_1_after = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert not torch.allclose(original_before.logits, adapter_1_after.logits)

        adapted_mistral.set_adapter("default")
        with adapted_mistral.disable_adapter():
            adapted_mistral.set_adapter("adapter 1")

        # Test that adapter 1 is active again.
        adapter_1_after_set = adapted_mistral(input_ids=input_ids, attention_mask=attention_mask, labels=target_ids)
        assert_close(adapter_1_after.logits, adapter_1_after_set.logits, rtol=0, atol=0)

    def test_use_cache(self) -> None:
        """Test that AdaptionPrompt works when Llama config use_cache=True."""
        torch.manual_seed(0)
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        original = LlamaForCausalLM(
            LlamaConfig(
                vocab_size=16,
                hidden_size=8,
                intermediate_size=8,
                num_hidden_layers=8,
                num_attention_heads=4,
                use_cache=False,
            )
        ).eval()
        adapted = get_peft_model(
            original, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted = adapted.to(self.torch_device)
        expected = adapted.generate(input_ids=input_ids, max_length=8)

        # Set use_cache = True and generate output again.
        adapted.base_model.config.use_cache = True
        actual = adapted.generate(input_ids=input_ids, max_length=8)
        assert_close(expected, actual, rtol=0, atol=0)

    @unittest.skipIf(not is_mistral_available(), "Mistral is not available")
    def test_use_cache_mistral(self) -> None:
        torch.manual_seed(0)
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        original = MistralForCausalLM(
            MistralConfig(
                vocab_size=16,
                hidden_size=8,
                intermediate_size=8,
                num_hidden_layers=8,
                num_attention_heads=4,
                num_key_value_heads=2,
                use_cache=False,
            )
        ).eval()
        adapted = get_peft_model(
            original, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted = adapted.to(self.torch_device)
        expected = adapted.generate(input_ids=input_ids, max_length=8)

        # Set use_cache = True and generate output again.
        adapted.base_model.config.use_cache = True
        actual = adapted.generate(input_ids=input_ids, max_length=8)
        assert_close(expected, actual, rtol=0, atol=0)

    def test_bf16_inference(self) -> None:
        if self.torch_device == "mps":
            return pytest.skip("Skipping bf16 test on MPS")

        """Test that AdaptionPrompt works when Llama using a half-precision model."""
        input_ids = torch.LongTensor([[1, 1, 1], [2, 1, 2]]).to(self.torch_device)
        original = LlamaForCausalLM.from_pretrained(
            "trl-internal-testing/tiny-random-LlamaForCausalLM", torch_dtype=torch.bfloat16
        )
        adapted = get_peft_model(
            original, AdaptionPromptConfig(adapter_layers=2, adapter_len=4, task_type="CAUSAL_LM")
        )
        adapted = adapted.to(self.torch_device)
        _ = adapted.generate(input_ids=input_ids)

    @unittest.expectedFailure
    def test_disable_adapter(self):
        llama_config = self._create_test_llama_config()
        model = LlamaForCausalLM(llama_config).to(self.torch_device)
        dummy_input = torch.LongTensor([[1, 1, 1]]).to(self.torch_device)
        output_before = model(dummy_input).logits

        config = AdaptionPromptConfig(adapter_layers=1, adapter_len=4, task_type="CAUSAL_LM")
        model = get_peft_model(model, config).to(self.torch_device)
        output_peft = model(dummy_input).logits
        # TODO currently this fails because scores are zeroed out:
        # https://github.com/huggingface/peft/blob/062d95a09eb5d1de35c0e5e23d4387daba99e2db/src/peft/tuners/adaption_prompt.py#L303
        # This is fine for users but makes it difficult to test if anything happens. In the future, we will have a clean
        # way to control initialization. Until then, this test is expected to fail.
        assert not torch.allclose(output_before, output_peft)

        with model.disable_adapter():
            output_peft_disabled = model(dummy_input).logits
        assert torch.allclose(output_before, output_peft_disabled)
