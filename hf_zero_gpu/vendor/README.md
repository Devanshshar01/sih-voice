# Vendored wheel: omegaconf 2.0.6 (metadata-repaired)

## Why this file exists

`fairseq==0.12.2` — the runtime required by the
[MMS-300M-AntiDeepfake](https://huggingface.co/nii-yamagishilab/mms-300m-anti-deepfake)
model card — declares `omegaconf<2.1` in its `install_requires`. The only
releases in that range are omegaconf **2.0.5** and **2.0.6**, and both were
published with metadata that modern pip considers invalid:

```
Requires-Dist: PyYAML (>=5.1.*)
```

`.*` is only a valid suffix for `==` and `!=`, so pip >= 24.1 (PEP 440 strict
parsing via `packaging`) rejects the candidate instead of warning:

```
WARNING: Ignoring version 2.0.6 of omegaconf since it has invalid metadata:
Requested omegaconf==2.0.6 from https://files.pythonhosted.org/.../omegaconf-2.0.6-py3-none-any.whl
has invalid metadata: .* suffix can only be used with `==` or `!=` operators
    PyYAML (>=5.1.*)
Please use pip<24.1 if you need to use this version.
ERROR: No matching distribution found for omegaconf==2.0.6
```

That is exactly the error that put the Space in `BUILD_ERROR`. Adding
`pip<24.1` to `requirements.txt` cannot fix it, because the Space base image
has already upgraded pip and pip resolves the requirements file with the
running pip (verified locally with pip 26.2.1: the failure reproduces; adding a
`pip<24.1` line changes nothing; pip 24.0 installs 2.0.6 successfully, which is
why the model card tells users to `conda install pip==24.0`).

## What was changed

Only one line of packaging metadata, no code:

```
- Requires-Dist: PyYAML (>=5.1.*)
+ Requires-Dist: PyYAML>=5.1
```

The unpacked `omegaconf/` sources are byte-identical to the upstream wheel, and
`RECORD` was regenerated so the wheel stays internally consistent.

| | |
|---|---|
| Upstream artifact | `omegaconf-2.0.6-py3-none-any.whl` from PyPI |
| Upstream sha256 | `9e349fd76819b95b47aa628edea1ff83fed5b25108608abdd6c7fdca188e302a` |
| Vendored sha256 | `a93c6b7dba48c30f1ffa4bf5a23d0b06eed1cf275f2070a555af3300fa506b17` |
| Size | 36 831 bytes |
| License | BSD-3-Clause (omegaconf / omry, unchanged — see the wheel's `LICENSE`) |
| Scope | HF ZeroGPU Space build only; Render production never installs it |

## How it is referenced

`hf_zero_gpu/requirements.txt` references this wheel through the public Space
URL using a direct `omegaconf @ ...` requirement. This avoids relying on the
Hugging Face build stage copying `vendor/` into `/app` while it mounts the
requirements file at `/tmp/requirements.txt`. The direct URL remains a valid
candidate for fairseq's `omegaconf<2.1` constraint.

## Removing this file

It can be deleted once `fairseq==0.12.2` is no longer required, i.e. only if the
anti-spoof checkpoint changes to one that loads without the fairseq/omegaconf
runtime.
