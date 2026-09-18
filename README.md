# Two AI security workshops you can run on your laptop

Hands-on labs for attacking AI systems, packaged so you can run them locally
with one command. No cloud account, no API key, no lecture.

**Workshop 1 — The Document Did It** · prompt injection, 7 exercises
Take over an AI assistant using nothing but text. No credentials, no exploit,
no code. You will make it ignore its instructions, call tools it should not,
and leak a secret out of the machine in an image URL.

**Workshop 2 — Shells From The Hub** · model supply chain, 7 exercises + 1 appendix
Build a malicious AI model, publish it to a model hub, and watch a machine you
have never touched execute your code. Ends with a root shell.

Everything runs in Docker on your own machine against a fake Hugging Face hub,
a fake corporate assistant, and a victim bot that really does load whatever you
publish.

---

## Quick start

```bash
git clone https://github.com/haxrbyte/ai-village-workshops
cd ai-village-workshops
./setup.sh
```

Then open the URL it prints (default <http://localhost:8080/start>).

**Everything is built on your machine.** There are no prebuilt images to pull
and no account to create. That is a deliberate choice for this particular
repo: a workshop about malicious model supply chains should not open by asking
you to trust someone else's binaries. Reproducibility comes from the pins —
base images by digest, every Python dependency from a lock file — which you
can read before you run anything.

The first build is the slow part, because `victim` installs PyTorch. After
that the layer cache makes it quick.

`setup.sh` checks your prerequisites, builds the images, fetches the language
model, starts everything, and verifies it with the project's own test gates. If
something is wrong it tells you the exact command to fix it.

## Requirements

|  |  |
|---|---|
| **Docker** | Desktop on macOS, Engine + Compose v2 on Linux |
| **Memory** | 6 GB available to Docker. On Colima: `colima start --cpu 4 --memory 8` |
| **Disk** | ~12 GB |
| **Platforms** | macOS (Apple Silicon or Intel), Linux x86_64 and arm64 |

Workshop 1 needs a language model. `setup.sh` handles it: on macOS it uses
Ollama on your host, on Linux it runs Ollama in a container. Don't want either?
`./setup.sh --canned` runs the whole of Workshop 1 with scripted replies — all
seven exercises still score, but only for the intended payloads; improvised
attacks get nothing back.

## Pick a team name — it matters even alone

The first thing the lab asks for is a team name, and it is not decoration. It
is the identity everything keys on: your own secrets directory, the flag you
are trying to steal, and the attribution for every callback that lands. If two
people share a lab, it is also what keeps their exercises apart.

The scoreboard is not a leaderboard so much as the **success signal** — when an
exfiltrated secret shows up there, that is how you know your attack landed
rather than silently failing.

## What is real and what is staged

Being precise about this, because the distinction is the whole value:

**Real:** the pickle deserialisation RCE, the `trust_remote_code` execution
path, the scanner evasion, the reverse shell, the prompt injections, and the
scanners themselves (`picklescan` and `modelscan` are real products, running
as their authors intended).

**Staged:** the company, the assistant, the model hub, the victim bot, and the
secrets you steal. All invented, all local.

Deliberately old pins make the vulnerabilities reachable. Every technique here
is already fixed upstream — the lab installs the *current* scanner too, so you
can watch it catch what the old one missed. See [SECURITY.md](SECURITY.md).

## Honest limitations

- **Workshop 1 is non-deterministic.** It drives a 3B model. On the author's
  own measurements it scores about 6 of 8, with exercises 4 and 5 flipping
  between runs. A bigger model was tried and scored *worse*. If an exercise
  fails once, try it again before assuming you got it wrong.
  Two caveats on that number, because it is easy to over-read: it was measured
  against the **notebook** wording of each payload, and this repo ships the web
  version, whose hints are worded differently — only 3 of 13 payload strings
  match verbatim. And it was measured on Apple Silicon; different hardware runs
  different kernels, so greedy decoding can diverge. Treat it as an indication,
  not a guarantee. `scripts/eval_workshop1.py --trials N` re-measures.
- **Workshop 2 exercise 8 is an optional appendix.** It needs a backdoored
  model that is not distributed here — you build it yourself from
  [`sleeper/README.md`](sleeper/README.md). It trains in 7-10 minutes on Apple
  Silicon, takes hours on Linux CPU, and **cannot be built on an Intel Mac**
  (MLX publishes no macOS-x86_64 wheel). Exercises 1-7 are unaffected, and the
  page tells you so rather than showing an error.

## Commands

```
make check        is the lab healthy?          make down     stop
make check-deep   ...plus network isolation    make reset    clear team state
make logs S=victim                             make up       start again
```

## Removing it

```bash
./uninstall.sh              # containers, networks, images built here, state
./uninstall.sh --all        # ...plus nginx/mailpit and the Docker build cache
./uninstall.sh --model      # ...also the ~2 GB Ollama model it pulled
./uninstall.sh --dry-run    # show what would go, change nothing
```

It prints exactly what it is about to remove and waits for confirmation.
Everything is scoped to this project's compose stack — nothing else on your
machine is touched unless you pass `--all` or `--model`, and both warn you
first, because the build cache and the model are shared with anything else
that uses them.

The seven built images come to roughly 3 GB, so this is worth running rather
than just deleting the directory.

## Instructor material

[`docs/instructor/`](docs/instructor/) has the answer keys for both workshops,
including measured hit rates for each payload and the failure modes that cost
the most time to debug. They are published deliberately — the working answers
are already reachable from the hint system, and a half-redacted workshop
teaches nothing.

## Licence

MIT, see [LICENSE](LICENSE). Third-party components and the model licences are
listed in [NOTICE](NOTICE) — note that Workshop 1's `llama3.2:3b` is under
Meta's Llama 3.2 Community Licence and is pulled, not redistributed.
