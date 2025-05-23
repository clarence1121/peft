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
import tempfile
import unittest

import torch

from peft import (
    AutoPeftModel,
    AutoPeftModelForCausalLM,
    AutoPeftModelForFeatureExtraction,
    AutoPeftModelForQuestionAnswering,
    AutoPeftModelForSeq2SeqLM,
    AutoPeftModelForSequenceClassification,
    AutoPeftModelForTokenClassification,
    PeftModel,
    PeftModelForCausalLM,
    PeftModelForFeatureExtraction,
    PeftModelForQuestionAnswering,
    PeftModelForSeq2SeqLM,
    PeftModelForSequenceClassification,
    PeftModelForTokenClassification,
)
from peft.utils import infer_device


class PeftAutoModelTester(unittest.TestCase):
    dtype = torch.float16 if infer_device() == "mps" else torch.bfloat16

    def test_peft_causal_lm(self):
        model_id = "peft-internal-testing/tiny-OPTForCausalLM-lora"
        model = AutoPeftModelForCausalLM.from_pretrained(model_id)
        assert isinstance(model, PeftModelForCausalLM)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModelForCausalLM.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModelForCausalLM)

        # check if kwargs are passed correctly
        model = AutoPeftModelForCausalLM.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForCausalLM)
        assert model.base_model.lm_head.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForCausalLM.from_pretrained(model_id, adapter_name, is_trainable, torch_dtype=self.dtype)

    def test_peft_causal_lm_extended_vocab(self):
        model_id = "peft-internal-testing/tiny-random-OPTForCausalLM-extended-vocab"
        model = AutoPeftModelForCausalLM.from_pretrained(model_id)
        assert isinstance(model, PeftModelForCausalLM)

        # check if kwargs are passed correctly
        model = AutoPeftModelForCausalLM.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForCausalLM)
        assert model.base_model.lm_head.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForCausalLM.from_pretrained(model_id, adapter_name, is_trainable, torch_dtype=self.dtype)

    def test_peft_seq2seq_lm(self):
        model_id = "peft-internal-testing/tiny_T5ForSeq2SeqLM-lora"
        model = AutoPeftModelForSeq2SeqLM.from_pretrained(model_id)
        assert isinstance(model, PeftModelForSeq2SeqLM)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModelForSeq2SeqLM.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModelForSeq2SeqLM)

        # check if kwargs are passed correctly
        model = AutoPeftModelForSeq2SeqLM.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForSeq2SeqLM)
        assert model.base_model.lm_head.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForSeq2SeqLM.from_pretrained(model_id, adapter_name, is_trainable, torch_dtype=self.dtype)

    def test_peft_sequence_cls(self):
        model_id = "peft-internal-testing/tiny_OPTForSequenceClassification-lora"
        model = AutoPeftModelForSequenceClassification.from_pretrained(model_id)
        assert isinstance(model, PeftModelForSequenceClassification)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModelForSequenceClassification.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModelForSequenceClassification)

        # check if kwargs are passed correctly
        model = AutoPeftModelForSequenceClassification.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForSequenceClassification)
        assert model.score.original_module.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForSequenceClassification.from_pretrained(
            model_id, adapter_name, is_trainable, torch_dtype=self.dtype
        )

    def test_peft_token_classification(self):
        model_id = "peft-internal-testing/tiny_GPT2ForTokenClassification-lora"
        model = AutoPeftModelForTokenClassification.from_pretrained(model_id)
        assert isinstance(model, PeftModelForTokenClassification)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModelForTokenClassification.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModelForTokenClassification)

        # check if kwargs are passed correctly
        model = AutoPeftModelForTokenClassification.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForTokenClassification)
        assert model.base_model.classifier.original_module.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForTokenClassification.from_pretrained(
            model_id, adapter_name, is_trainable, torch_dtype=self.dtype
        )

    def test_peft_question_answering(self):
        model_id = "peft-internal-testing/tiny_OPTForQuestionAnswering-lora"
        model = AutoPeftModelForQuestionAnswering.from_pretrained(model_id)
        assert isinstance(model, PeftModelForQuestionAnswering)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModelForQuestionAnswering.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModelForQuestionAnswering)

        # check if kwargs are passed correctly
        model = AutoPeftModelForQuestionAnswering.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForQuestionAnswering)
        assert model.base_model.qa_outputs.original_module.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForQuestionAnswering.from_pretrained(
            model_id, adapter_name, is_trainable, torch_dtype=self.dtype
        )

    def test_peft_feature_extraction(self):
        model_id = "peft-internal-testing/tiny_OPTForFeatureExtraction-lora"
        model = AutoPeftModelForFeatureExtraction.from_pretrained(model_id)
        assert isinstance(model, PeftModelForFeatureExtraction)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModelForFeatureExtraction.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModelForFeatureExtraction)

        # check if kwargs are passed correctly
        model = AutoPeftModelForFeatureExtraction.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModelForFeatureExtraction)
        assert model.base_model.model.decoder.embed_tokens.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModelForFeatureExtraction.from_pretrained(
            model_id, adapter_name, is_trainable, torch_dtype=self.dtype
        )

    def test_peft_whisper(self):
        model_id = "peft-internal-testing/tiny_WhisperForConditionalGeneration-lora"
        model = AutoPeftModel.from_pretrained(model_id)
        assert isinstance(model, PeftModel)

        with tempfile.TemporaryDirectory() as tmp_dirname:
            model.save_pretrained(tmp_dirname)

            model = AutoPeftModel.from_pretrained(tmp_dirname)
            assert isinstance(model, PeftModel)

        # check if kwargs are passed correctly
        model = AutoPeftModel.from_pretrained(model_id, torch_dtype=self.dtype)
        assert isinstance(model, PeftModel)
        assert model.base_model.model.model.encoder.embed_positions.weight.dtype == self.dtype

        adapter_name = "default"
        is_trainable = False
        # This should work
        _ = AutoPeftModel.from_pretrained(model_id, adapter_name, is_trainable, torch_dtype=self.dtype)
