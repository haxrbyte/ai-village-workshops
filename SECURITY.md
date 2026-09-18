# Responsible use

**This lab is deliberately vulnerable. That is the entire point.** It builds
working malware and runs it. Read this before you start.

## Run it on a machine you own

Everything binds to localhost and the containers that execute your code have no
route off the machine (below). But you are still running attack code on your
own hardware. Do not run this on a work laptop you do not control, on shared
infrastructure, or anywhere a compliance team would be surprised to find it.

## What actually has network access

| Container | Internet? | Why |
|---|---|---|
| `victim`, `shellbox` | **No** | These execute attendee-authored code — arbitrary pickles and a real `/bin/sh`. They sit on an `internal: true` Docker network and can reach only `hub` and `listener`. |
| `hub`, `listener`, `nginx` | Yes | They straddle both networks so the sandboxed pair can reach them. |
| `mailmate` | Yes | It calls your local Ollama. |

`make check-deep` asserts the isolation rather than assuming it: it tries to
reach the internet *from inside* `victim` and fails the run if it succeeds.

## What you are being handed

Concretely, so nobody is surprised:

- **Pickle deserialisation RCE.** Builders for `__reduce__` payloads, including
  a scanner-evasion variant (protocol 2 with the STOP opcode removed).
- **A real reverse shell.** Workshop 2 exercise 7 gives you a root shell in the
  `victim` container. It is an ordinary Python reverse shell; only the target
  is fixed to the lab.
- **`trust_remote_code` / `auto_map` execution.** Loading a model config that
  runs code, with no weights involved.
- **A recipe for backdooring a language model.** The exercise 8 appendix. The
  trained weights are **not** distributed; the pipeline and dataset are.
- **Prompt-injection payloads**, measured, with their hit rates.

These techniques are public and documented. What this repo adds is a safe place
to run them and see them work.

## The pinned versions are the exercise, not neglect

`picklescan==0.0.15`, and the deliberately old library pins elsewhere, are there
so the vulnerability is reachable. **Every technique demonstrated here is already
fixed upstream** — the lab also installs the current `picklescan` so you can
watch it catch what the old one missed.

Please do not file reports that our pinned dependencies are outdated. They are
outdated on purpose and an upgrade would silently repair the bug being taught.

## The fictional names are fictional

`northwind`, `evilcorp`, `northwind.local` and the model repo names are
invented. They exist only inside this lab, served by the fake hub that runs in
a container next to you.

Every repo path here is resolved through `HF_ENDPOINT`, which points at that
fake hub. **Do not run the lab's payloads with `HF_ENDPOINT` unset** — a name
like `evilcorp/llama-3-8b-instruct-fast` would then be resolved against the
real huggingface.co. The `victim` container additionally sets
`HF_HUB_OFFLINE=1` so that a mistake there cannot reach the internet at all.

Two specifics worth stating, because we checked rather than assumed:

- **`evilcorp` is a real organisation name on Hugging Face and it is not
  ours.** It was registered in 2022, holds no models, and has nothing to do
  with this project. Nothing in these workshops points at it over the network,
  and a config field that did (a leftover from a talk demo, pointing at
  `evilcorp/fast-attn@main`) was removed before publication for exactly that
  reason. Do not create repos under that name.
- **`northwind` is not registered.** If you fork this and change the fiction,
  pick names you control, and do not register these ones to "reserve" them.

The phishing URL baked into the exercise-8 appendix uses the RFC 2606
`.invalid` TLD, which can never be delegated to anyone. That was a deliberate
fix: an earlier version used a plausible-looking real TLD that turned out to
resolve to a live third party's hosts.

## Reporting something

If you find a way this lab harms the person running it — a container escape, a
path that reaches the host, a payload that is not contained — please open an
issue, or contact the maintainer privately if you would rather not post it.
