---
name: ai-worker
description: Use when writing evidence-led articles from real materials.
version: 1.3.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [writing, content, cross-platform, evidence, audience, publishing]
    related_skills: [strategic-thinking-dialogue, obsidian-markdown]
---

# AI Worker: Evidence-Led Content System

## Overview

Use this skill to turn a real discovery into content that earns attention by changing the reader's understanding, not by copying another writer's voice or manufacturing conflict.

The stable author capabilities are:

- **Experimenter** — brings real trials, observations, choices, failures, and first-hand material.
- **Judgment-maker** — identifies what matters, what is uncertain, and what changes after the evidence.
- **Explainer** — makes mechanisms, evidence boundaries, and practical implications legible.

These are capabilities, not a fixed persona. Do not force all three into every piece.

## Authorial Stance

The default author stance is:

> Enter the real scene; do not trust a smooth story too quickly. For a complete-looking report, an impressive showcase, or a convenient causal explanation, ask what it specifically proves, what it leaves out, and under which conditions it fails. A conclusion may be direct, but its strength must match the evidence. The article does not decide for the reader; it helps the reader recognize the same pattern earlier next time.

This is a stable way of seeing and judging, not a performance persona. Do not turn it into fixed catchphrases, permanent skepticism, manufactured conflict, or reflexive takedowns. Evidence may confirm a claim; the task is to make the confirmation and its boundary equally legible.

## When to Use

- The user asks to write an article, long-form post, content draft, or turn a real experiment, observation, research finding, or business experience into an article.
- A user has a real tool test, experiment, work incident, research finding, business observation, or changed mind worth sharing.
- The user explicitly asks for a thread, short-video entry, visual post, or platform-specific adaptation **after or alongside** the article task.

Do not use for pure fiction, generic SEO copy, inventing a personal experience that did not occur, or automatically generating separate versions for every publishing platform.

## Core Rule: Discovery Before Audience and Hook

Never begin by locking a narrow audience, inventing a viral hook, or pre-writing a contrarian conclusion.

Use this sequence:

```text
real material
→ what actually changed in the author's understanding
→ why that matters beyond the author
→ who may benefit from understanding it
→ the reader's cognitive takeaway
→ article structure and paragraph flow
→ only if explicitly requested: a separate platform form
```

Audience may differ by piece. A recurring audience can be a tendency, never a rule that distorts unrelated material.

## Material Ledger

Before drafting, capture:

| Field | Required question |
|---|---|
| Raw material | What was directly tested, seen, researched, or experienced? |
| Trigger moment | What precise fact, failure, surprise, or contradiction changed the author's mind? |
| Facts | What can be verified from original records, sources, output, screenshots, or data? |
| Inferences | What explanation follows, and what would overturn it? |
| Unknowns | What important evidence is missing, inaccessible, or unverified? |
| Reader payoff | What judgment, action, question, or model can the reader carry away? |
| Potential beneficiaries | Who benefits from that payoff in this specific piece? |
| Platform context | How will the article coexist with short video or be published, and does that change only its entry or evidence density? |

Default deliverable: one complete article. Do not create separate short-video scripts, threads, visual posts, or platform rewrites unless the user explicitly requests them.

If the ledger is thin, either gather material or explicitly limit the claim. Do not use smooth prose to hide evidence gaps.

### Material Sufficiency and Honest Fallback

Before expanding a non-fiction piece, identify the one to three **load-bearing judgments**: if a judgment were removed, would the article's reader payoff still stand? For each one, record:

- whether it is fact, first-hand observation, inference, hypothesis, or unknown;
- the material that supports it;
- its scope or limiting condition; and
- any live alternative explanation.

Do not use a fixed item count as a proxy for sufficiency. One primary record can matter more than many derivative sources; many same-source items may still leave the judgment unsupported.

When a planned long-form piece has an unsupported load-bearing judgment, follow this order:

1. Gather available public material and reassess the judgment.
2. If the missing material is unique to the author, ask at most three precise questions whose answers could change the article's conclusion.
3. If it remains unsupported, narrow the question, lower the claim strength, make the unknown explicit, or deliver a shorter bounded answer.

Never use repeated explanation, invented scenes, generalized examples, or a smoother narrative to fill the missing evidence.

### Load-Bearing Relationship Check

Check the relationships that carry the article's conclusion, not every sentence. A claim such as “X caused Y,” “X proves Y,” “X is based on Y,” or “an actor did Y because of X” must lead back to one of:

- direct material;
- an explicitly labelled inference with a plausible mechanism and stated alternatives; or
- an explicit unknown or verification need.

Chronological proximity, same-paragraph co-occurrence, a showcase, or one successful task does not establish a load-bearing relationship. First-hand observation may establish the author's position, but must not be presented as a public fact or group-level conclusion.

## Draft Architecture

A strong piece usually moves:

```text
specific real moment
→ first concrete payoff
→ why the moment matters
→ evidence, process, counterexample, and limitation
→ transferable model or action
```

Each paragraph should have one dominant job: scene, explanation, evidence, counterargument, action, or transition.

### Natural Entries

Choose an entry from the source material, not from a stock hook library:

- scene: a real operation or moment;
- result: a surprising but evidenced outcome;
- question: a genuine unresolved question;
- experience: a changed mind or failed attempt;
- observation: a public pattern tied to a concrete example.

Do not default to formulas such as “you thought X, but actually Y,” “the real danger is not X but Y,” or permanent adversarial framing. Use them only when the source material truly warrants them.

## Voice and Legibility

- Write from the author's actual position: “I saw / tested / concluded / still do not know.”
- Do not speak on behalf of a nation, industry, user group, or ideological camp merely because of one personal test.
- Personal judgment is allowed; distinguish it from verified fact.
- Avoid imitating a named creator's catchphrases, distinctive punctuation habits, or persona; this does not prohibit the author's own deliberate punctuation or rhythm.
- Mobile readability does not mean every sentence becomes its own paragraph. Let argument units determine paragraph length. Use isolated short paragraphs only at genuine turns, not as a quota.
- Prefer concrete detail over generic “AI-style” summaries and perfectly uniform numbered frameworks.

## Evidence Boundaries

For research, tools, benchmarks, and products, separate:

```text
Official claim: what a provider says it can do
Showcase ceiling: what selected samples prove it has done
Benchmark: performance on a particular task set, metric, version, and evaluation method
Personal test: results in this task, with these inputs and conditions
Production use: repeatability, controllability, cost, failure modes, repair path, and deliverable rate
```

Never let one layer substitute for another.

For a real tool failure, state the narrow observed failure first. For example: “a three-shot instruction became one continuous shot,” not “the model cannot follow direction.” Then state what more testing would be needed for a general claim.

### Business and Strategic Causality

A chronological sequence is not a causal explanation. For business, policy, industry, and strategic articles, explicitly separate:

```text
fact: what a filing, regulator, court, dataset, or company announcement establishes
mechanism: how an effect could plausibly travel
inference: which motive or explanation is consistent with the facts
alternative explanations: other causes that remain live
unknown: what public evidence cannot establish
```

Do not replace one smooth but unsupported story with another. For example, correcting “a sanction forced a company into a new industry” does not prove that a particular product, ecosystem, or brand capability caused the move. Narrow the article question to what the evidence can actually establish.

When judging whether a company has “entered” or “established itself” in a new market, do not use one signal as a proxy for all others:

```text
performance showcase / record → a bounded engineering or marketing signal
interest / reservation → interest and partial conversion intent
customer delivery → capacity and fulfillment
margin → price and direct cost structure
operating profit → economics after R&D, channel, and organizational costs
quality and service → long-term trust and durability
```

Mark each signal's scope. A company can pass one stage without having passed the next.

## Optional Distribution Adaptation

Treat short video and platform conditions as the **publication environment** for the article, not as an automatic requirement to create a parallel text for every platform.

The article must independently provide its full reasoning, evidence, limits, and conclusion. When readers arrive after short video, the opening may acknowledge the concrete scene or question that earned their attention, then provide the deeper evidence and reasoning they could not get from the video.

Only when the user explicitly asks for a short-video script, thread, visual post, Q&A answer, or platform adaptation should you create a separate asset. In that case, preserve the same factual core and do not mechanically shorten the article.

| Explicitly requested form | Job | Minimum payoff |
|---|---|---|
| Short video | Make the scene, result, or failure visible | One real, verifiable finding |
| Short post / thread | Give an observation worth discussing | Why the observation matters |
| Visual post | Make a comparison, process, or framework saveable | One usable layer of explanation |
| Q&A answer | Answer the named question first | Reasoning and source boundaries |

Short-form content must not hold essential information hostage to force a click. The article must deliver more evidence and explanation than any entry promised.

## Revision Mode for Existing Drafts

Use this mode only when the user supplies an existing draft and asks to revise, polish, tighten, restructure, or diagnose it. Do not run it by default when drafting a new article, researching, or outlining.

### 1. Protect Before Editing

Before changing prose, identify content that cannot silently drift:

- numbers, dates, versions, units, ranges, and comparisons;
- people, organizations, products, responsibility, and attribution;
- quotes, sources, commands, paths, model names, and key terms;
- conditions, negations, limits, causal relationships, and uncertainty;
- first-hand task conditions, attempts, and observation scope;
- the author's distinctive vocabulary, colloquial phrasing, emotional traces, and first-person judgment lines — HIGHEST protection level. Identified per draft from the author's actual material; this skill presets no fixed word list.

These are protected against silent change, not against correction. If an item is wrong or the user asks to change it, state what changed and why. When the user authorizes only in-place cleanup and a factual correction would alter meaning, flag the correction separately rather than silently making it; provide the exact correction and reason, then preserve the user's decision.

Register replacement is a substantive change, not cleanup. Formalizing colloquialisms, replacing emotional words, or translating a distinctive phrase into neutral written language changes what the reader sees of the author. Treat it exactly like a factual correction: flag it with the exact replacement and reason, and preserve the user's decision. Never silently de-colloquialize.

### 2. Declare the Revision Scope

- **bounded** — default. Suggest deletions or structural changes, but list whole-sentence or whole-paragraph deletions as recommendations rather than silently removing text that may carry judgment, rhythm, or authorial trace.
- **in-place** — use when the user asks to preserve the text or not delete sentences. Clean within sentences only; do not reorder the structure.
- **structural** — use only with user authorization or when the current structure cannot carry the article's judgment.

Do not let platform convention, length alone, or a generic “AI-like” impression select the scope.

### 3. Diagnose Structure Before Prose

Separate:

- **structure** — the article question, supported load-bearing judgments, paragraph roles, progression, counterexamples, limits, and whether the ending matches the argument;
- **prose** — late subjects or actions, unclear reference, empty elevation, ineffective transitions, overly uniform rhythm, and formulaic summaries.

Do not deeply polish prose while a structural defect still makes the argument unreliable or unclear.

### 4. Protect Authorial Trace

Treat concrete firsthand phrasing, explainable hesitation, qualification, self-correction, judgment position, and naturally uneven rhythm as possible authorial trace rather than automatic defects.

- When uncertain, change less and mark the change as reversible.
- Do not manufacture a sharper line, balanced parallelism, a prettier metaphor, or a more vivid scene the author did not provide.
- Do not remove first person, local roughness, or a tone particle merely because a smoother substitute is available.
- Authorial trace never overrides truth: factual error, causal overreach, or serious ambiguity must still be identified.
- If successive user feedback reverses direction (too verbose → too sparse → too impersonal), stop full rewrites. Switch to in-place scope: change only what the latest feedback names, keep every untouched sentence byte-identical. Direction feedback is not a license to overcorrect.

### 5. Two Read-Back Passes

First read for fidelity: protected content, facts, relationships, scope, limits, terms, register, and key paragraph roles.

Only then read for residual prose friction: stock openings, empty conclusions, vague judgment, unnecessary signposts, or mechanically uniform paragraph and sentence rhythm. Do not normalize intentional rhythm, legitimate parallelism, or the author's deliberate punctuation merely for variation. This second pass makes light corrections only; it does not reopen full rewriting or add facts.

For Chinese text, judge friction with the CGED (Chinese Grammatical Error Diagnosis) four error types instead of relying on feel: **missing** (subject, object, or connective absent), **redundant** (same number or fact repeated in one passage; parenthetical restatement), **wrong** (inconsistent wording for one concept nearby; two verbs fused into an unreadable unit), **word order** (broken verb-object pairing). Read each sentence aloud; a pause landing on the wrong boundary is the signal. Apply the controlled-Chinese principles that fit narrative and report prose: one term per concept (repetition is not a defect), one main clause per sentence, resolvable reference (avoid unattached 该/其/此/上述), explicit causal and conditional connectives. Syntax edits must not touch content units: distinctive vocabulary, judgment lines, numbers, facts — every changed clause must map word-for-word back to the draft.

### 6. Scan the Impact of Material Changes

If a revision changes a fact, data point, causal statement, conclusion, or scope, re-read the title, opening, ending, and affected paragraphs for conflict. If it changes only word order, punctuation, connective wording, or obvious repetition, local read-back is enough.

### Revision Delivery

Return one recommended revision. When the change is substantive, include a concise change list: what changed, why, any reversible change, and any unresolved factual or structural gap. If a substantive deletion removes an error-bearing claim, identify both the deletion and the underlying error. Do not default to multiple variants, a score, a claim of being free of “AI style,” or a publication verdict.

## Feedback Boundary

Use the user's explicit correction, rejection, or retention decision first for the current article. A single edit, one topic, or an external evaluator's preference does not define a durable writing preference.

Only when a similar preference appears across separate articles should it become a candidate rule, phrased as an observable behavior rather than a persona or catchphrase. Ask the user to confirm before treating that candidate as durable. External metrics, critics, or pattern detectors may surface a local concern, but must never become a writing target or automatically shape the author's voice.

## Self-Check

### L0 — Truth
- [ ] Key claims are labelled in the draft logic as fact, inference, hypothesis, or opinion.
- [ ] First-hand experience and sources are not fabricated.
- [ ] Important gaps are disclosed rather than silently omitted.
- [ ] A broad conclusion is not drawn from a narrow test.
- [ ] Each load-bearing causal, capability, or scope relationship can be traced to direct material, a clearly labelled inference with mechanism and alternatives, or an explicit unknown.

### L1 — Reader Contract
- [ ] The opening comes from a real moment, not a replaceable formula.
- [ ] The first section gives a genuine payoff quickly.
- [ ] The ending gives a judgment tool, action, or clarified question, not only a slogan.

### L2 — Authorial Integrity
- [ ] The piece does not borrow another creator's persona.
- [ ] It does not inflate a personal observation into a group-level claim.
- [ ] It makes the article's real judgment visible; it does not hide behind neutral fact listing when the evidence supports a bounded conclusion.
- [ ] The conclusion's strength matches its evidence, limitations, and alternative explanations.
- [ ] Paragraph density fits the piece; no mechanical one-sentence-per-paragraph rhythm.
- [ ] Repeated frameworks, duplicate checklists, and stacked “closing lines” are removed.
- [ ] Chinese prose passes the CGED four-type syntax read-back (missing / redundant / wrong / word order); every fix maps back to the draft's content units.

### L3 — Distribution and Learning
- [ ] The article can stand alone; short video or platform context is used only to improve its entry and depth, not to replace its reasoning.
- [ ] Separate platform assets exist only if the user explicitly requested them.
- [ ] When separate assets are requested, their factual core matches the article and their form matches the platform.
- [ ] The primary goal is named: reach, attention, saves, relationship, or action.
- [ ] Post-publication feedback distinguishes exposure, dwell, value, relationship, and action rather than treating clicks as success.
- [ ] A user correction from one article is not silently generalized into a long-term voice rule.

## Common Pitfalls

1. **Narrative polish mistaken for research quality.** A complete-looking report may rest on too few or too narrow sources. Show source coverage, missing categories, and independence before trusting conclusions.
2. **Showcase mistaken for production readiness.** A product launch video proves a ceiling in selected conditions, not success on the author's task. Test task compliance and repeatability.
3. **Fixed-reader overfitting.** Do not force every topic into one customer segment. Determine beneficiaries after understanding the material.
4. **Sharpness mistaken for judgment.** A judgment can be tentative, calm, or explanatory. Do not manufacture an enemy or grand stance.
5. **Checklist prose.** A framework is useful only once it changes the reader's decision. Avoid restating the same five questions twice in different wording.
6. **Undisclosed implementation status.** When describing a system response, distinguish completed changes from ongoing work and planned work.
7. **Timeline mistaken for causality.** Events occurring near each other do not prove one caused the other. Check the legal or operational mechanism, direct statements, alternative motives, and what the evidence cannot establish.
8. **One signal mistaken for market establishment.** A record, reservation total, viral launch, or one profitable period cannot stand in for delivery, service, quality, and sustained economics.

## Completion Criteria

A content draft is ready for author review when it has:

- a completed material ledger;
- supported, limited, or explicitly unknown load-bearing judgments;
- a draft with fact / inference / unknown boundaries preserved;
- at least one clear reader payoff;
- platform entries separated from the main article;
- a self-check against L0–L3;
- separate platform assets only when explicitly requested;
- no invented benchmark, test parameter, source, outcome, or audience reaction.
