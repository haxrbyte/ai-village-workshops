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

`northwind`, `evilcorp`, `northwind.local` and the model repo names are invented
and are **not registered** on any real model hub. Do not create them on a real
hub, and do not run the lab's payloads with `HF_ENDPOINT` unset — the `victim`
container sets `HF_HUB_OFFLINE=1` precisely so a mistake there cannot reach the
real internet. The phishing URL baked into the exercise-8 appendix uses the
RFC 2606 `.invalid` TLD, which can never be delegated to anyone.

## Reporting something

If you find a way this lab harms the person running it — a container escape, a
path that reaches the host, a payload that is not contained — please open an
issue, or contact the maintainer privately if you would rather not post it.
