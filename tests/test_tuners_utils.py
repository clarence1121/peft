#!/usr/bin/env python3

# coding=utf-8
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
import re
import unittest
from copy import deepcopy

import pytest
import torch
from diffusers import StableDiffusionPipeline
from parameterized import parameterized
from torch import nn
from transformers import AutoModel, AutoModelForCausalLM, AutoModelForSeq2SeqLM, BitsAndBytesConfig

from peft import (
    AdaptionPromptConfig,
    IA3Config,
    LoHaConfig,
    LoraConfig,
    PromptTuningConfig,
    VeraConfig,
    get_layer_status,
    get_model_status,
    get_peft_model,
)
from peft.tuners.tuners_utils import (
    BaseTunerLayer,
    _maybe_include_all_linear_layers,
    check_target_module_exists,
    inspect_matched_modules,
)
from peft.utils import INCLUDE_LINEAR_LAYERS_SHORTHAND

from .testing_utils import require_bitsandbytes, require_torch_gpu


# Implements tests for regex matching logic common for all BaseTuner subclasses, and
# tests for correct behaviour with different config kwargs for BaseTuners (Ex: feedforward for IA3, etc) and
# tests for utility function to include all linear layers

REGEX_TEST_CASES = [
    # tuple of
    # 1. key
    # 2. target_modules
    # 3. layers_to_transform
    # 4. layers_pattern
    # 5. expected result
    # some basic examples
    ("", [], None, None, False),
    ("", ["foo"], None, None, False),
    ("foo", [], None, None, False),
    ("foo", ["foo"], None, None, True),
    ("foo", ["bar"], None, None, False),
    ("foo", ["foo", "bar"], None, None, True),
    # with regex
    ("foo", "foo", None, None, True),
    ("foo", ".*oo", None, None, True),
    ("foo", "fo.*", None, None, True),
    ("foo", ".*bar.*", None, None, False),
    ("foobar", ".*oba.*", None, None, True),
    # with layers_to_transform
    ("foo.bar.1.baz", ["baz"], [1], ["bar"], True),
    ("foo.bar.1.baz", ["baz"], [0], ["bar"], False),
    ("foo.bar.1.baz", ["baz"], [2], ["bar"], False),
    ("foo.bar.10.baz", ["baz"], [0], ["bar"], False),
    ("foo.bar.10.baz", ["baz"], [1], ["bar"], False),
    ("foo.bar.1.baz", ["baz"], [0, 1, 2], ["bar"], True),
    ("foo.bar.1.baz", ["baz", "spam"], [1], ["bar"], True),
    ("foo.bar.1.baz", ["baz", "spam"], [0, 1, 2], ["bar"], True),
    # empty layers_to_transform
    ("foo.bar.7.baz", ["baz"], [], ["bar"], True),
    ("foo.bar.7.baz", ["baz"], None, ["bar"], True),
    # empty layers_pattern
    ("foo.whatever.1.baz", ["baz"], [1], [], True),
    ("foo.whatever.1.baz", ["baz"], [0], [], False),
    ("foo.whatever.1.baz", ["baz"], [1], "", True),
    ("foo.whatever.1.baz", ["baz"], [0], "", False),
    ("foo.whatever.1.baz", ["baz"], [1], None, True),
    ("foo.whatever.1.baz", ["baz"], [0], None, False),
    # some realistic examples: transformers model
    ("transformer.h.1.attn.attention.q_proj.foo", ["q_proj"], None, [], False),
    ("transformer.h.1.attn.attention.q_proj", [], None, [], False),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj"], None, [], True),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj", "v_proj"], None, [], True),
    ("transformer.h.1.attn.attention.resid_dropout", ["q_proj", "v_proj"], None, [], False),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj"], [1], ["h"], True),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj"], [0], ["h"], False),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj"], [2], ["h"], False),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj"], [0, 1, 2], ["h"], True),
    ("transformer.h.1.attn.attention.q_proj", ["q_proj", "v_proj"], [0, 1, 2], ["h"], True),
    ("foo.bar.q_proj", ["q_proj"], None, [], True),
    ("foo.bar.1.baz", ["baz"], [1], ["foo"], False),
    # other corner cases. For ex, below is a case where layers_pattern
    # is one of the target nn.modules
    ("foo.bar.1.baz", ["baz"], [1], ["baz"], False),
    # here, layers_pattern is 'bar', but only keys that contain '.bar' are valid.
    ("bar.1.baz", ["baz"], [1], ["bar"], False),
    ("foo.bar.001.baz", ["baz"], [1], ["bar"], True),
    ("foo.bar.1.spam.2.baz", ["baz"], [1], ["bar"], True),
    ("foo.bar.2.spam.1.baz", ["baz"], [1], ["bar"], False),
    # some realistic examples: module using nn.Sequential
    # for the below test case, key should contain '.blocks' to be valid, because of how layers_pattern is matched
    ("blocks.1.weight", ["weight"], [1], ["blocks"], False),
    ("blocks.1.bias", ["weight"], [1], ["blocks"], False),
    ("mlp.blocks.1.weight", ["weight"], [1], ["blocks"], True),
    ("mlp.blocks.1.bias", ["weight"], [1], ["blocks"], False),
]

MAYBE_INCLUDE_ALL_LINEAR_LAYERS_TEST_CASES = [
    # model_name, model_type, initial_target_modules, expected_target_modules
    # test for a causal Llama model
    (
        "HuggingFaceH4/tiny-random-LlamaForCausalLM",
        "causal",
        INCLUDE_LINEAR_LAYERS_SHORTHAND,
        ["k_proj", "v_proj", "q_proj", "o_proj", "down_proj", "up_proj", "gate_proj"],
    ),
    # test for a Llama model without the LM head
    (
        "HuggingFaceH4/tiny-random-LlamaForCausalLM",
        "base",
        INCLUDE_LINEAR_LAYERS_SHORTHAND,
        ["k_proj", "v_proj", "q_proj", "o_proj", "down_proj", "up_proj", "gate_proj"],
    ),
    # test for gpt2 with Conv1D layers
    ("hf-internal-testing/tiny-random-gpt2", "causal", INCLUDE_LINEAR_LAYERS_SHORTHAND, ["c_attn", "c_proj", "c_fc"]),
    # test for T5 model
    (
        "hf-internal-testing/tiny-random-t5",
        "seq2seq",
        INCLUDE_LINEAR_LAYERS_SHORTHAND,
        ["k", "q", "v", "o", "wi", "wo"],
    ),
    # test for GPTNeoX. output module list should exclude classification head - which is named as "embed_out" instead of the usual "lm_head" for GPTNeoX
    (
        "hf-internal-testing/tiny-random-GPTNeoXForCausalLM",
        "causal",
        INCLUDE_LINEAR_LAYERS_SHORTHAND,
        ["query_key_value", "dense", "dense_h_to_4h", "dense_4h_to_h"],
    ),
]

# tests for a few args that should remain unchanged
MAYBE_INCLUDE_ALL_LINEAR_LAYERS_TEST_INTERNALS = [
    # initial_target_modules, expected_target_modules
    (["k_proj"], ["k_proj"]),
    # test with target_modules as None
    (None, None),
    # test with target_modules as a regex expression
    (".*(q_proj|v_proj)$", ".*(q_proj|v_proj)$"),
]

BNB_QUANTIZATIONS = [("4bit",), ("8bit",)]
BNB_TEST_CASES = [(x + y) for x in MAYBE_INCLUDE_ALL_LINEAR_LAYERS_TEST_CASES for y in BNB_QUANTIZATIONS]


class PeftCustomKwargsTester(unittest.TestCase):
    r"""
    Test if the PeftModel is instantiated with correct behaviour for custom kwargs. This includes:
    - test if regex matching works correctly
    - test if adapters handle custom kwargs the right way e.g. IA3 for `feedforward_modules`

    """

    transformers_class_map = {"causal": AutoModelForCausalLM, "seq2seq": AutoModelForSeq2SeqLM, "base": AutoModel}

    @parameterized.expand(REGEX_TEST_CASES)
    def test_regex_matching_valid(self, key, target_modules, layers_to_transform, layers_pattern, expected_result):
        # We use a LoRA Config for testing, but the regex matching function is common for all BaseTuner subclasses.
        # example model_id for config initialization. key is matched only against the target_modules given, so this can be any model
        model_id = "peft-internal-testing/tiny-OPTForCausalLM-lora"
        config = LoraConfig(
            base_model_name_or_path=model_id,
            target_modules=target_modules,
            layers_pattern=layers_pattern,
            layers_to_transform=layers_to_transform,
        )
        actual_result = bool(check_target_module_exists(config, key))
        assert actual_result == expected_result

    def test_module_matching_lora(self):
        # peft models that have a module matching method to inspect the matching modules to allow
        # users to easily debug their configuration. Here we only test a single case, not all possible combinations of
        # configs that could exist. This is okay as the method calls `check_target_module_exists` internally, which
        # has been extensively tested above.
        model_id = "hf-internal-testing/tiny-random-BloomForCausalLM"
        model = AutoModel.from_pretrained(model_id)
        # by default, this model matches query_key_value
        config = LoraConfig()
        peft_model = get_peft_model(model, config)

        output = inspect_matched_modules(peft_model)  # inspects default adapter for peft_model
        matched = output["matched"]
        expected = [
            "h.0.self_attention.query_key_value",
            "h.1.self_attention.query_key_value",
            "h.2.self_attention.query_key_value",
            "h.3.self_attention.query_key_value",
            "h.4.self_attention.query_key_value",
        ]
        assert matched == expected  # module lists should match exactly

        # no overlap with matched modules
        unmatched = output["unmatched"]
        for key in expected:
            assert key not in unmatched

    def test_feedforward_matching_ia3(self):
        model_id = "hf-internal-testing/tiny-random-T5ForConditionalGeneration"
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
        # simple example for just one t5 block for testing
        config_kwargs = {
            "target_modules": ".*encoder.*block.0.*(SelfAttention|EncDecAttention|DenseReluDense).(k|q|v|wo|wi)$",
            "feedforward_modules": ["wo", "wi"],
        }
        config = IA3Config(base_model_name_or_path=model_id, **config_kwargs)
        peft_model = get_peft_model(model, config)
        output = inspect_matched_modules(peft_model)  # inspects default adapter for peft_model
        matched = output["matched"]
        expected = [
            "encoder.block.0.layer.0.SelfAttention.q",
            "encoder.block.0.layer.0.SelfAttention.k",
            "encoder.block.0.layer.0.SelfAttention.v",
            "encoder.block.0.layer.1.DenseReluDense.wi",
            "encoder.block.0.layer.1.DenseReluDense.wo",
        ]
        expected_feedforward = [
            "encoder.block.0.layer.1.DenseReluDense.wi",
            "encoder.block.0.layer.1.DenseReluDense.wo",
        ]
        assert matched == expected  # not required since we do similar checks above, but just to be sure
        module_dict = dict(model.named_modules())
        for key in matched:
            module = module_dict[key]
            if key in expected_feedforward:
                assert module.is_feedforward
            else:  # other IA3 modules should not be marked as feedforward
                assert not module.is_feedforward

    @parameterized.expand(MAYBE_INCLUDE_ALL_LINEAR_LAYERS_TEST_CASES)
    def test_maybe_include_all_linear_layers_lora(
        self, model_id, model_type, initial_target_modules, expected_target_modules
    ):
        model = self.transformers_class_map[model_type].from_pretrained(model_id)
        config_cls = LoraConfig
        self._check_match_with_expected_target_modules(
            model_id, model, config_cls, initial_target_modules, expected_target_modules
        )

    @parameterized.expand(BNB_TEST_CASES)
    @require_torch_gpu
    @require_bitsandbytes
    def test_maybe_include_all_linear_layers_lora_bnb(
        self, model_id, model_type, initial_target_modules, expected_target_modules, quantization
    ):
        if quantization == "4bit":
            config_kwargs = {"quantization_config": BitsAndBytesConfig(load_in_4bit=True)}
        elif quantization == "8bit":
            config_kwargs = {"quantization_config": BitsAndBytesConfig(load_in_8bit=True)}
        model = self.transformers_class_map[model_type].from_pretrained(model_id, device_map="auto", **config_kwargs)
        config_cls = LoraConfig
        self._check_match_with_expected_target_modules(
            model_id, model, config_cls, initial_target_modules, expected_target_modules
        )

    def _check_match_with_expected_target_modules(
        self, model_id, model, config_cls, initial_target_modules, expected_target_modules
    ):
        """
        Helper function for the test for `_maybe_include_all_linear_layers`
        """
        actual_config = config_cls(base_model_name_or_path=model_id, target_modules=initial_target_modules)
        expected_config = config_cls(base_model_name_or_path=model_id, target_modules=expected_target_modules)
        model_copy = deepcopy(model)
        actual_model = get_peft_model(model, peft_config=actual_config)
        expected_model = get_peft_model(model_copy, peft_config=expected_config)
        expected_model_module_dict = dict(expected_model.named_modules())
        # compare the two models and assert that all layers are of the same type
        for name, actual_module in actual_model.named_modules():
            expected_module = expected_model_module_dict[name]
            assert type(actual_module) == type(expected_module)

    def test_maybe_include_all_linear_layers_ia3_loha(self):
        model_id, initial_target_modules, expected_target_modules = (
            "HuggingFaceH4/tiny-random-LlamaForCausalLM",
            INCLUDE_LINEAR_LAYERS_SHORTHAND,
            ["k_proj", "v_proj", "q_proj", "o_proj", "down_proj", "up_proj", "gate_proj"],
        )
        model_ia3 = AutoModelForCausalLM.from_pretrained(model_id)
        model_loha = deepcopy(model_ia3)
        config_classes = [IA3Config, LoHaConfig]
        models = [model_ia3, model_loha]
        for config_cls, model in zip(config_classes, models):
            self._check_match_with_expected_target_modules(
                model_id, model, config_cls, initial_target_modules, expected_target_modules
            )

    @parameterized.expand(MAYBE_INCLUDE_ALL_LINEAR_LAYERS_TEST_INTERNALS)
    def test_maybe_include_all_linear_layers_internals(self, initial_target_modules, expected_target_modules):
        model_id = "HuggingFaceH4/tiny-random-LlamaForCausalLM"
        model = AutoModelForCausalLM.from_pretrained(model_id)
        config = LoraConfig(base_model_name_or_path=model_id, target_modules=initial_target_modules)
        new_config = _maybe_include_all_linear_layers(config, model)
        if isinstance(expected_target_modules, list):
            # assert that expected and actual target_modules have the same items
            assert set(new_config.target_modules) == set(expected_target_modules)
        else:
            assert new_config.target_modules == expected_target_modules

    def test_maybe_include_all_linear_layers_diffusion(self):
        model_id = "hf-internal-testing/tiny-stable-diffusion-torch"
        model = StableDiffusionPipeline.from_pretrained(model_id)
        config = LoraConfig(base_model_name_or_path=model_id, target_modules="all-linear")
        with pytest.raises(
            ValueError,
            match="Only instances of PreTrainedModel support `target_modules='all-linear'`",
        ):
            model.unet = get_peft_model(model.unet, config)


class MLP(nn.Module):
    def __init__(self, bias=True):
        super().__init__()
        self.lin0 = nn.Linear(10, 20, bias=bias)
        self.relu = nn.ReLU()
        self.drop = nn.Dropout(0.5)
        self.lin1 = nn.Linear(20, 2, bias=bias)
        self.sm = nn.LogSoftmax(dim=-1)


class TestTargetedModuleNames(unittest.TestCase):
    """Check that the attribute targeted_module_names is correctly set.

    This checks LoRA and IA³, but this should be sufficient, testing all other tuners is not necessary.
    """

    def test_one_targeted_module_regex(self):
        model = MLP()
        model = get_peft_model(model, LoraConfig(target_modules="lin0"))
        assert model.targeted_module_names == ["lin0"]

    def test_two_targeted_module_regex(self):
        model = MLP()
        model = get_peft_model(model, LoraConfig(target_modules="lin.*"))
        assert model.targeted_module_names == ["lin0", "lin1"]

    def test_one_targeted_module_list(self):
        model = MLP()
        model = get_peft_model(model, LoraConfig(target_modules=["lin0"]))
        assert model.targeted_module_names == ["lin0"]

    def test_two_targeted_module_list(self):
        model = MLP()
        model = get_peft_model(model, LoraConfig(target_modules=["lin0", "lin1"]))
        assert model.targeted_module_names == ["lin0", "lin1"]

    def test_ia3_targeted_module_regex(self):
        model = MLP()
        model = get_peft_model(model, IA3Config(target_modules=".*lin.*", feedforward_modules=".*lin.*"))
        assert model.targeted_module_names == ["lin0", "lin1"]

    def test_ia3_targeted_module_list(self):
        model = MLP()
        model = get_peft_model(model, IA3Config(target_modules=["lin0", "lin1"], feedforward_modules=["lin0", "lin1"]))
        assert model.targeted_module_names == ["lin0", "lin1"]

    def test_realistic_example(self):
        model = AutoModelForCausalLM.from_pretrained("hf-internal-testing/tiny-random-BloomForCausalLM")
        config = LoraConfig(task_type="CAUSAL_LM")
        model = get_peft_model(model, config)
        expected = [
            f"transformer.h.{i}.self_attention.query_key_value" for i in range(len(model.base_model.transformer.h))
        ]
        assert model.targeted_module_names == expected


class TestModelAndLayerStatus:
    """Check the methods `get_layer_status` and `get_model_status`.`

    Note that we only test LoRA here but the same logic should work for other tuner types (if they support the
    corresponding features like merging).

    """

    @pytest.fixture
    def small_model(self):
        class SmallModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.lin0 = nn.Linear(10, 10)
                self.lin1 = nn.Linear(10, 10)

        config = LoraConfig(target_modules="lin0")
        return get_peft_model(SmallModel(), config)

    @pytest.fixture
    def large_model(self):
        class LargeModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.lin0 = nn.Linear(10, 10)
                self.conv0 = nn.Conv2d(3, 10, 3)
                self.emb0 = nn.Embedding(10, 10)
                self.lin1 = nn.Linear(10, 10)
                self.conv1 = nn.Conv2d(3, 10, 3)
                self.emb1 = nn.Embedding(10, 10)

        config0 = LoraConfig(target_modules=["lin0", "conv1", "emb0"])
        config1 = LoraConfig(target_modules=["lin0", "lin1"], r=16)
        model = get_peft_model(LargeModel(), config0)
        model.add_adapter("other", config1)
        return model

    ################
    # layer status #
    ################

    def test_layer_names_small(self, small_model):
        layer_status = small_model.get_layer_status()
        expected = ["model.lin0"]
        assert [status.name for status in layer_status] == expected

    def test_layer_names_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = sorted([status.name for status in layer_status])
        expected = ["model.conv1", "model.emb0", "model.lin0", "model.lin1"]
        assert result == expected

    def test_module_type_small(self, small_model):
        layer_status = small_model.get_layer_status()
        assert [status.module_type for status in layer_status] == ["lora.Linear"]

    def test_module_type_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = sorted([status.module_type for status in layer_status])
        expected = ["lora.Conv2d", "lora.Embedding", "lora.Linear", "lora.Linear"]
        assert result == expected

    def test_enabled_small(self, small_model):
        layer_status = small_model.get_layer_status()
        assert [status.enabled for status in layer_status] == [True]

    def test_enabled_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = [status.enabled for status in layer_status]
        expected = [True, True, True, True]
        assert result == expected

    def test_enabled_irregular(self, large_model):
        # this is an invalid state, but we should still test it
        # disable a single layer
        for module in large_model.modules():
            if isinstance(module, BaseTunerLayer):
                module.enable_adapters(False)
                break

        layer_status = large_model.get_layer_status()
        result = [status.enabled for status in layer_status]
        expected = [False, True, True, True]
        assert result == expected

    def test_active_adapters_small(self, small_model):
        layer_status = small_model.get_layer_status()
        assert [status.active_adapters for status in layer_status] == [["default"]]

    def test_active_adapters_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = [status.active_adapters for status in layer_status]
        # note: as currently implemented, the active adapter can be an adapter that does not exist on this specific
        # layer, for instance, layer 3 (i.e. index 2) only has the "other" adapter but "default" is still shown as the
        # active adapter
        expected = [["default"], ["default"], ["default"], ["default"]]
        assert result == expected

        # switch to "other"
        large_model.set_adapter("other")
        layer_status = large_model.get_layer_status()
        result = [status.active_adapters for status in layer_status]
        expected = [["other"], ["other"], ["other"], ["other"]]

    def test_merge_adapters_small(self, small_model):
        layer_status = small_model.get_layer_status()
        assert [status.merged_adapters for status in layer_status] == [[]]
        assert [status.available_adapters for status in layer_status] == [["default"]]

        # now merge "default"
        small_model.merge_adapter(["default"])
        layer_status = small_model.get_layer_status()
        assert [status.merged_adapters for status in layer_status] == [["default"]]
        assert [status.available_adapters for status in layer_status] == [["default"]]

    def test_merge_adapters_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = [status.merged_adapters for status in layer_status]
        assert result == [[], [], [], []]

        # now merge "default"
        large_model.merge_adapter(["default"])
        layer_status = large_model.get_layer_status()
        result = [status.merged_adapters for status in layer_status]
        # default is on layer 0, 1, and 3
        assert result == [["default"], ["default"], [], ["default"]]

        # now merge "other"
        large_model.unmerge_adapter()
        large_model.merge_adapter(["other"])
        layer_status = large_model.get_layer_status()
        result = [status.merged_adapters for status in layer_status]
        # other is on layer 0 and 2
        assert result == [["other"], [], ["other"], []]

        # now merge both
        large_model.merge_adapter(["default", "other"])
        layer_status = large_model.get_layer_status()
        result = [status.merged_adapters for status in layer_status]
        # default is on layer 0, 1, and 3, other is on layer 0 and 2
        assert result == [["other", "default"], ["default"], ["other"], ["default"]]

    def test_requires_grad_small(self, small_model):
        layer_status = small_model.get_layer_status()
        assert [status.requires_grad for status in layer_status] == [{"default": True}]

    def test_requires_grad_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = [status.requires_grad for status in layer_status]
        # default is on layer 0, 1, and 3, other is on layer 0 and 2
        expected = [{"default": True, "other": False}, {"default": True}, {"other": False}, {"default": True}]
        assert result == expected

        # now activate "other"
        large_model.set_adapter("other")
        layer_status = large_model.get_layer_status()
        result = [status.requires_grad for status in layer_status]
        expected = [{"default": False, "other": True}, {"default": False}, {"other": True}, {"default": False}]
        assert result == expected

    def test_requires_grad_irregular(self, large_model):
        # inject an embedding layer with requires_grad=False
        # this is an invalid state, but we should still test it
        lora_embedding_A = nn.Parameter(torch.zeros(10, 10))
        lora_embedding_B = nn.Parameter(torch.zeros(10, 10))
        lora_embedding_A.requires_grad = False
        lora_embedding_B.requires_grad = False
        large_model.base_model.model.lin0.lora_embedding_A["default"] = lora_embedding_A
        large_model.base_model.model.lin0.lora_embedding_B["default"] = lora_embedding_B

        layer_status = large_model.get_layer_status()
        result = [status.requires_grad for status in layer_status]
        expected = [{"default": "irregular", "other": False}, {"default": True}, {"other": False}, {"default": True}]
        assert result == expected

    def test_available_adapters_small(self, small_model):
        layer_status = small_model.get_layer_status()
        result = [status.available_adapters for status in layer_status]
        expected = [["default"]]
        assert result == expected

    def test_available_adapters_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = [status.available_adapters for status in layer_status]
        expected = [["default", "other"], ["default"], ["other"], ["default"]]
        assert result == expected

    def test_devices_all_cpu_small(self, small_model):
        layer_status = small_model.get_layer_status()
        result = [status.devices for status in layer_status]
        expected = [{"default": ["cpu"]}]
        assert result == expected

    def test_devices_all_cpu_large(self, large_model):
        layer_status = large_model.get_layer_status()
        result = [status.devices for status in layer_status]
        expected = [
            {"default": ["cpu"], "other": ["cpu"]},
            {"default": ["cpu"]},
            {"other": ["cpu"]},
            {"default": ["cpu"]},
        ]
        assert result == expected

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="No CUDA device available.")
    def test_devices_all_cuda_large(self, large_model):
        large_model.to("cuda")
        layer_status = large_model.get_layer_status()
        result = [status.devices for status in layer_status]
        expected = [
            {"default": ["cuda"], "other": ["cuda"]},
            {"default": ["cuda"]},
            {"other": ["cuda"]},
            {"default": ["cuda"]},
        ]
        assert result == expected

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="No CUDA device available.")
    def test_devices_cpu_and_cuda_large(self, large_model):
        # move the embedding layer to CUDA
        large_model.model.lin0.lora_A["default"] = large_model.model.lin0.lora_A["default"].to("cuda")
        layer_status = large_model.get_layer_status()
        result = [status.devices for status in layer_status]
        expected = [
            {"default": ["cpu", "cuda"], "other": ["cpu"]},
            {"default": ["cpu"]},
            {"other": ["cpu"]},
            {"default": ["cpu"]},
        ]
        assert result == expected

    ################
    # model status #
    ################

    def test_base_model_type_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.base_model_type == "SmallModel"

    def test_base_model_type_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.base_model_type == "LargeModel"

    def test_base_model_type_transformers_automodel(self):
        # ensure that this also works with transformers AutoModels
        model_id = "google/flan-t5-small"
        model = AutoModel.from_pretrained(model_id)
        model = get_peft_model(model, LoraConfig())
        model_status = model.get_model_status()
        assert model_status.base_model_type == "T5Model"

    def test_adapter_model_type_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.adapter_model_type == "LoraModel"

    def test_adapter_model_type_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.adapter_model_type == "LoraModel"

    def test_peft_types_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.peft_types == {"default": "LORA"}

    def test_peft_types_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.peft_types == {"default": "LORA", "other": "LORA"}

    def test_nb_params_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.trainable_params == 160
        assert model_status.total_params == 380

    def test_nb_params_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.trainable_params == 616
        assert model_status.total_params == 2236

    def test_num_adapter_layers_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.num_adapter_layers == 1

    def test_num_adapter_layers_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.num_adapter_layers == 4

    def test_model_enabled_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.enabled is True

    def test_model_enabled_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.enabled is True

    def test_model_disabled_small(self, small_model):
        small_model.disable_adapter_layers()
        model_status = small_model.get_model_status()
        assert model_status.enabled is False

    def test_model_disabled_large(self, large_model):
        large_model.disable_adapter_layers()
        model_status = large_model.get_model_status()
        assert model_status.enabled is False

    def test_model_enabled_irregular(self, large_model):
        # this is an invalid state, but we should still test it
        # disable a single layer
        for module in large_model.modules():
            if isinstance(module, BaseTunerLayer):
                module.enable_adapters(False)
                break

        model_status = large_model.get_model_status()
        assert model_status.enabled == "irregular"

    def test_model_active_adapters_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.active_adapters == ["default"]

    def test_model_active_adapters_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.active_adapters == ["default"]

        large_model.set_adapter("other")
        model_status = large_model.get_model_status()
        assert model_status.active_adapters == ["other"]

    def test_model_active_adapters_irregular(self, large_model):
        # this is an invalid state, but we should still test it
        # disable a single layer
        for module in large_model.modules():
            if isinstance(module, BaseTunerLayer):
                # switch a single layer's active adapter from default to other
                if module.active_adapters == ["default"]:
                    module._active_adapter = "other"
                    assert module.active_adapters == ["other"]
                    break

        model_status = large_model.get_model_status()
        assert model_status.active_adapters == "irregular"

    def test_model_merged_adapters_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.merged_adapters == []

        small_model.merge_adapter()
        model_status = small_model.get_model_status()
        assert model_status.merged_adapters == ["default"]

        small_model.unmerge_adapter()
        model_status = small_model.get_model_status()
        assert model_status.merged_adapters == []

    def test_model_merged_adapters_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.merged_adapters == []

        large_model.merge_adapter(["default"])
        model_status = large_model.get_model_status()
        assert model_status.merged_adapters == ["default"]

        large_model.unmerge_adapter()
        large_model.merge_adapter(["other"])
        model_status = large_model.get_model_status()
        assert model_status.merged_adapters == ["other"]

        large_model.unmerge_adapter()
        large_model.merge_adapter(["default", "other"])
        model_status = large_model.get_model_status()
        assert model_status.merged_adapters == ["default", "other"]

    def test_model_merged_adapters_irregular(self, large_model):
        # this is an invalid state, but we should still test it
        # by merging only lin0 of "default", we end up in a irregular state, because not all "default" layers are merged
        large_model.base_model.lin0.merge(["default"])

        model_status = large_model.get_model_status()
        assert model_status.merged_adapters == "irregular"

    def test_model_requires_grad_model_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.requires_grad == {"default": True}

    def test_model_requires_grad_model_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.requires_grad == {"default": True, "other": False}

        large_model.set_adapter("other")
        model_status = large_model.get_model_status()
        assert model_status.requires_grad == {"default": False, "other": True}

    def test_model_requires_grad_model_irregular(self, large_model):
        # inject an embedding layer with requires_grad=False
        # this is an invalid state, but we should still test it
        lora_embedding_A = nn.Parameter(torch.zeros(10, 10))
        lora_embedding_B = nn.Parameter(torch.zeros(10, 10))
        lora_embedding_A.requires_grad = False
        lora_embedding_B.requires_grad = False
        large_model.base_model.model.lin0.lora_embedding_A["default"] = lora_embedding_A
        large_model.base_model.model.lin0.lora_embedding_B["default"] = lora_embedding_B

        model_status = large_model.get_model_status()
        assert model_status.requires_grad == {"default": "irregular", "other": False}

    def test_model_available_adapters_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.available_adapters == ["default"]

    def test_model_available_adapters_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.available_adapters == ["default", "other"]

    def test_model_devices_all_cpu_small(self, small_model):
        model_status = small_model.get_model_status()
        assert model_status.devices == {"default": ["cpu"]}

    def test_model_devices_all_cpu_large(self, large_model):
        model_status = large_model.get_model_status()
        assert model_status.devices == {"default": ["cpu"], "other": ["cpu"]}

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="No CUDA device available.")
    def test_model_devices_all_cuda_large(self, large_model):
        large_model.to("cuda")
        model_status = large_model.get_model_status()
        assert model_status.devices == {"default": ["cuda"], "other": ["cuda"]}

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="No CUDA device available.")
    def test_model_devices_cpu_and_cuda_large(self, large_model):
        # move the embedding layer to CUDA
        large_model.model.lin0.lora_A["default"] = large_model.model.lin0.lora_A["default"].to("cuda")
        model_status = large_model.get_model_status()
        assert model_status.devices == {"default": ["cpu", "cuda"], "other": ["cpu"]}

    def test_loha_model(self):
        # ensure that this also works with non-LoRA, it's not necessary to test all tuners
        class SmallModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.lin0 = nn.Linear(10, 10)
                self.lin1 = nn.Linear(10, 10)

        base_model = SmallModel()
        config = LoHaConfig(target_modules=["lin0", "lin1"], init_weights=False)
        model = get_peft_model(base_model, config)

        model_status = model.get_model_status()
        layer_status = model.get_layer_status()

        assert model_status.base_model_type == "SmallModel"
        assert model_status.adapter_model_type == "LoHaModel"
        assert model_status.peft_types == {"default": "LOHA"}
        assert model_status.trainable_params == 640
        assert model_status.total_params == 860
        assert model_status.num_adapter_layers == 2
        assert model_status.enabled is True
        assert model_status.active_adapters == ["default"]
        assert model_status.merged_adapters == []
        assert model_status.requires_grad == {"default": True}
        assert model_status.available_adapters == ["default"]
        assert model_status.devices == {"default": ["cpu"]}

        layer_status0 = layer_status[0]
        assert len(layer_status) == 2
        assert layer_status0.name == "model.lin0"
        assert layer_status0.module_type == "loha.Linear"
        assert layer_status0.enabled is True
        assert layer_status0.active_adapters == ["default"]
        assert layer_status0.merged_adapters == []
        assert layer_status0.requires_grad == {"default": True}
        assert layer_status0.available_adapters == ["default"]
        assert layer_status0.devices == {"default": ["cpu"]}

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="No CUDA device available.")
    def test_vera_model(self):
        # let's also test VeRA because it uses BufferDict
        class SmallModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.lin0 = nn.Linear(10, 10)
                self.lin1 = nn.Linear(10, 10)

        base_model = SmallModel()
        config = VeraConfig(target_modules=["lin0", "lin1"], init_weights=False)
        model = get_peft_model(base_model, config)

        # move the buffer dict to CUDA
        model.lin0.vera_A["default"] = model.lin0.vera_A["default"].to("cuda")

        model_status = model.get_model_status()
        layer_status = model.get_layer_status()

        assert model_status.base_model_type == "SmallModel"
        assert model_status.adapter_model_type == "VeraModel"
        assert model_status.peft_types == {"default": "VERA"}
        assert model_status.trainable_params == 532
        assert model_status.total_params == 752
        assert model_status.num_adapter_layers == 2
        assert model_status.enabled is True
        assert model_status.active_adapters == ["default"]
        assert model_status.merged_adapters == []
        assert model_status.requires_grad == {"default": True}
        assert model_status.available_adapters == ["default"]
        assert model_status.devices == {"default": ["cpu", "cuda"]}

        layer_status0 = layer_status[0]
        assert len(layer_status) == 2
        assert layer_status0.name == "model.lin0"
        assert layer_status0.module_type == "vera.Linear"
        assert layer_status0.enabled is True
        assert layer_status0.active_adapters == ["default"]
        assert layer_status0.merged_adapters == []
        assert layer_status0.requires_grad == {"default": True}
        assert layer_status0.available_adapters == ["default"]
        assert layer_status0.devices == {"default": ["cpu", "cuda"]}

    ###################
    # non-PEFT models #
    ###################

    def test_transformers_model(self):
        model_id = "peft-internal-testing/gpt2-lora-random"
        # note that loading through AutoModelForCausalLM.from_pretrained does not enable training mode, hence
        # requires_grad=False
        model = AutoModelForCausalLM.from_pretrained(model_id)
        model_status = get_model_status(model)
        layer_status = get_layer_status(model)

        assert model_status.base_model_type == "GPT2LMHeadModel"
        assert model_status.adapter_model_type == "None"
        assert model_status.peft_types == {}
        assert model_status.trainable_params == 0
        assert model_status.total_params == 124734720
        assert model_status.num_adapter_layers == 12
        assert model_status.enabled is True
        assert model_status.active_adapters == ["default"]
        assert model_status.merged_adapters == []
        assert model_status.requires_grad == {"default": False}
        assert model_status.available_adapters == ["default"]
        assert model_status.devices == {"default": ["cpu"]}

        layer_status0 = layer_status[0]
        assert len(layer_status) == 12
        assert layer_status0.name == "transformer.h.0.attn.c_attn"
        assert layer_status0.module_type == "lora.Linear"
        assert layer_status0.enabled is True
        assert layer_status0.active_adapters == ["default"]
        assert layer_status0.merged_adapters == []
        assert layer_status0.requires_grad == {"default": False}
        assert layer_status0.available_adapters == ["default"]
        assert layer_status0.devices == {"default": ["cpu"]}

    def test_model_with_injected_layers(self, large_model):
        model = large_model.base_model.model
        model_status = get_model_status(model)
        layer_status = get_layer_status(model)

        assert model_status.base_model_type == "other"
        assert model_status.adapter_model_type == "None"
        assert model_status.peft_types == {}
        assert model_status.trainable_params == 616
        assert model_status.total_params == 2236
        assert model_status.num_adapter_layers == 4
        assert model_status.enabled is True
        assert model_status.active_adapters == ["default"]
        assert model_status.merged_adapters == []
        assert model_status.requires_grad == {"default": True, "other": False}
        assert model_status.available_adapters == ["default", "other"]
        assert model_status.devices == {"default": ["cpu"], "other": ["cpu"]}

        layer_status1 = layer_status[1]
        assert len(layer_status) == 4
        assert layer_status1.name == "emb0"
        assert layer_status1.module_type == "lora.Embedding"
        assert layer_status1.enabled is True
        assert layer_status1.active_adapters == ["default"]
        assert layer_status1.merged_adapters == []
        assert layer_status1.requires_grad == {"default": True}
        assert layer_status1.available_adapters == ["default"]
        assert layer_status1.devices == {"default": ["cpu"]}

    ###############
    # error cases #
    ###############

    def test_vanilla_model_raises(self):
        model = nn.Linear(10, 10)
        # note: full error message is longer
        with pytest.raises(ValueError, match="No adapter layers found in the model"):
            get_layer_status(model)

        with pytest.raises(ValueError, match="No adapter layers found in the model"):
            get_model_status(model)

    def test_transformer_model_without_adapter_raises(self):
        model = AutoModelForCausalLM.from_pretrained("gpt2")
        # note: full error message is longer
        with pytest.raises(ValueError, match="No adapter layers found in the model"):
            get_layer_status(model)

        with pytest.raises(ValueError, match="No adapter layers found in the model"):
            get_model_status(model)

    def test_prefix_tuning(self):
        model = AutoModelForSeq2SeqLM.from_pretrained("hf-internal-testing/tiny-random-BartForConditionalGeneration")
        config = PromptTuningConfig(task_type="SEQ_2_SEQ_LM", num_virtual_tokens=10)
        model = get_peft_model(model, config)

        # note: full error message is longer
        with pytest.raises(TypeError, match=re.escape("get_layer_status() got an invalid PeftModel instance")):
            model.get_layer_status()

        with pytest.raises(TypeError, match=re.escape("get_model_status() got an invalid PeftModel instance")):
            model.get_model_status()

    def test_adaption_prompt(self):
        model = AutoModelForCausalLM.from_pretrained("HuggingFaceH4/tiny-random-LlamaForCausalLM")
        config = AdaptionPromptConfig(adapter_layers=1, adapter_len=4)
        model = get_peft_model(model, config)

        # note: full error message is longer
        with pytest.raises(TypeError, match=re.escape("get_layer_status() got an invalid PeftModel instance")):
            model.get_layer_status()

        with pytest.raises(TypeError, match=re.escape("get_model_status() got an invalid PeftModel instance")):
            model.get_model_status()

    def test_mixed_model_raises(self):
        class SimpleNet(nn.Module):
            def __init__(self, bias=True):
                super().__init__()
                # note: out_features must be > rank or else OFT will be an identity transform
                self.lin0 = nn.Linear(10, 20, bias=bias)
                self.relu = nn.ReLU()
                self.lin1 = nn.Linear(20, 16, bias=bias)

            def forward(self, X):
                X = X.float()
                X = self.lin0(X)
                X = self.relu(X)
                X = self.lin1(X)
                return X

        base_model = SimpleNet()
        config0 = LoraConfig(target_modules=["lin0"], init_lora_weights=False)
        config1 = LoHaConfig(target_modules=["lin0", "lin1"], init_weights=False)
        model = get_peft_model(base_model, config0, adapter_name="adapter0", mixed="mixed")
        model.add_adapter("adapter1", config1)

        # note: full error message is longer
        with pytest.raises(TypeError, match="get_layer_status is not supported for PeftMixedModel"):
            model.get_layer_status()

        with pytest.raises(TypeError, match="get_model_status is not supported for PeftMixedModel"):
            model.get_model_status()
