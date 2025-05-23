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

# PEFT integrations

PEFT's practical benefits extends to other Hugging Face libraries like [Diffusers](https://hf.co/docs/diffusers) and [Transformers](https://hf.co/docs/transformers). One of the main benefits of PEFT is that an adapter file generated by a PEFT method is a lot smaller than the original model, which makes it super easy to manage and use multiple adapters. You can use one pretrained base model for multiple tasks by simply loading a new adapter finetuned for the task you're solving. Or you can combine multiple adapters with a text-to-image diffusion model to create new effects.

This tutorial will show you how PEFT can help you manage adapters in Diffusers and Transformers.

## Diffusers

Diffusers is a generative AI library for creating images and videos from text or images with diffusion models. LoRA is an especially popular training method for diffusion models because you can very quickly train and share diffusion models to generate images in new styles. To make it easier to use and try multiple LoRA models, Diffusers uses the PEFT library to help manage different adapters for inference.

For example, load a base model and then load the [artificialguybr/3DRedmond-V1](https://huggingface.co/artificialguybr/3DRedmond-V1) adapter for inference with the [`load_lora_weights`](https://huggingface.co/docs/diffusers/v0.24.0/en/api/loaders/lora#diffusers.loaders.LoraLoaderMixin.load_lora_weights) method. The `adapter_name` argument in the loading method is enabled by PEFT and allows you to set a name for the adapter so it is easier to reference.

```py
import torch
from diffusers import DiffusionPipeline

pipeline = DiffusionPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=torch.float16
).to("cuda")
pipeline.load_lora_weights(
    "peft-internal-testing/artificialguybr__3DRedmond-V1", 
    weight_name="3DRedmond-3DRenderStyle-3DRenderAF.safetensors", 
    adapter_name="3d"
)
image = pipeline("sushi rolls shaped like kawaii cat faces").images[0]
image
```

<div class="flex justify-center">
    <img src="https://huggingface.co/datasets/ybelkada/documentation-images/resolve/main/test-lora-diffusers.png"/>
</div>

Now let's try another cool LoRA model, [ostris/super-cereal-sdxl-lora](https://huggingface.co/ostris/super-cereal-sdxl-lora). All you need to do is load and name this new adapter with `adapter_name`, and use the [`set_adapters`](https://huggingface.co/docs/diffusers/api/loaders/unet#diffusers.loaders.UNet2DConditionLoadersMixin.set_adapters) method to set it as the currently active adapter.

```py
pipeline.load_lora_weights(
    "ostris/super-cereal-sdxl-lora", 
    weight_name="cereal_box_sdxl_v1.safetensors", 
    adapter_name="cereal"
)
pipeline.set_adapters("cereal")
image = pipeline("sushi rolls shaped like kawaii cat faces").images[0]
image
```

<div class="flex justify-center">
    <img src="https://huggingface.co/datasets/ybelkada/documentation-images/resolve/main/test-lora-diffusers-2.png"/>
</div>

Finally, you can call the [`disable_lora`](https://huggingface.co/docs/diffusers/api/loaders/unet#diffusers.loaders.UNet2DConditionLoadersMixin.disable_lora) method to restore the base model.

```py
pipeline.disable_lora()
```

Learn more about how PEFT supports Diffusers in the [Inference with PEFT](https://huggingface.co/docs/diffusers/tutorials/using_peft_for_inference) tutorial.

## Transformers

🤗 [Transformers](https://hf.co/docs/transformers) is a collection of pretrained models for all types of tasks in all modalities. You can load these models for training or inference. Many of the models are large language models (LLMs), so it makes sense to integrate PEFT with Transformers to manage and train adapters.

Load a base pretrained model to train.

```py
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained("facebook/opt-350m")
```

Next, add an adapter configuration to specify how to adapt the model parameters. Call the [`~PeftModel.add_adapter`] method to add the configuration to the base model.

```py
from peft import LoraConfig

peft_config = LoraConfig(
    lora_alpha=16,
    lora_dropout=0.1,
    r=64,
    bias="none",
    task_type="CAUSAL_LM"
)
model.add_adapter(peft_config)
```

Now you can train the model with Transformer's [`~transformers.Trainer`] class or whichever training framework you prefer.

To use the newly trained model for inference, the [`~transformers.AutoModel`] class uses PEFT on the backend to load the adapter weights and configuration file into a base pretrained model.

```py
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained("peft-internal-testing/opt-350m-lora")
```

Alternatively, you can use transformers [Pipelines](https://huggingface.co/docs/transformers/en/main_classes/pipelines) to load the model for conveniently running inference:

```py
from transformers import pipeline

model = pipeline("text-generation", "peft-internal-testing/opt-350m-lora")
print(model("Hello World"))
```

If you're interested in comparing or using more than one adapter, you can call the [`~PeftModel.add_adapter`] method to add the adapter configuration to the base model. The only requirement is the adapter type must be the same (you can't mix a LoRA and LoHa adapter).

```py
from transformers import AutoModelForCausalLM
from peft import LoraConfig

model = AutoModelForCausalLM.from_pretrained("facebook/opt-350m")
model.add_adapter(lora_config_1, adapter_name="adapter_1")
```

Call [`~PeftModel.add_adapter`] again to attach a new adapter to the base model.

```py
model.add_adapter(lora_config_2, adapter_name="adapter_2")
```

Then you can use [`~PeftModel.set_adapter`] to set the currently active adapter.

```py
model.set_adapter("adapter_1")
output = model.generate(**inputs)
print(tokenizer.decode(output_disabled[0], skip_special_tokens=True))
```

To disable the adapter, call the [disable_adapters](https://github.com/huggingface/transformers/blob/4e3490f79b40248c53ee54365a9662611e880892/src/transformers/integrations/peft.py#L313) method.

```py
model.disable_adapters()
```

The [enable_adapters](https://github.com/huggingface/transformers/blob/4e3490f79b40248c53ee54365a9662611e880892/src/transformers/integrations/peft.py#L336) can be used to enable the adapters again.

If you're curious, check out the [Load and train adapters with PEFT](https://huggingface.co/docs/transformers/main/peft) tutorial to learn more.
