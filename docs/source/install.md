<!--Copyright 2023 The HuggingFace Team. All rights reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

⚠️ Note that this file is in Markdown but contain specific syntax for our doc-builder (similar to MDX) that may not be
rendered properly in your Markdown viewer.

-->

# Installation

Before you start, you will need to setup your environment, install the appropriate packages, and configure 🤗 PEFT. 🤗 PEFT is tested on **Python 3.8+**.

🤗 PEFT is available on PyPI, as well as GitHub:

## PyPI

To install 🤗 PEFT from PyPI:

```bash
pip install peft
```

## Source

New features that haven't been released yet are added every day, which also means there may be some bugs. To try them out, install from the GitHub repository:

```bash
pip install git+https://github.com/huggingface/peft
```

If you're working on contributing to the library or wish to play with the source code and see live 
results as you run the code, an editable version can be installed from a locally-cloned version of the 
repository:

```bash
git clone https://github.com/huggingface/peft
cd peft
pip install -e .
```
