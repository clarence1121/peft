<!--Copyright 2024 The HuggingFace Team. All rights reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

⚠️ Note that this file is in Markdown but contain specific syntax for our doc-builder (similar to MDX) that may not be
rendered properly in your Markdown viewer.

-->

# Model merge

PEFT provides several internal utilities for [merging LoRA adapters](../developer_guides/model_merging) with the TIES and DARE methods.

[[autodoc]] utils.merge_utils.prune

[[autodoc]] utils.merge_utils.calculate_majority_sign_mask

[[autodoc]] utils.merge_utils.disjoint_merge

[[autodoc]] utils.merge_utils.task_arithmetic

[[autodoc]] utils.merge_utils.ties

[[autodoc]] utils.merge_utils.dare_linear

[[autodoc]] utils.merge_utils.dare_ties
