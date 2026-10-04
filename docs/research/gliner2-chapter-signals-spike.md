# GLiNER2.5 Chapter Signals spike

Date: 2026-10-02

This spike asks whether a small local encoder can cheaply create an exact,
source-linked scaffold before Qwen performs Bookinator's combined Chapter
Reading. It is an experiment, not a production pipeline contract.

## Runtime

The published `gliner2==2.0.0` package did not contain the upstream
compatibility normalization for legacy list-valued tokenizer metadata. The
experiment therefore used official GLiNER2 commit
`55656fbfa01d3d4a77485e1a1eeeaf682990ccdf` in an isolated Python 3.12 virtual
environment. Do not add this dependency to Bookinator's ordinary installation
until a fixed release can be pinned and tested.

## Carmilla Chapter I results

The test source was the canonical extracted Chapter I Markdown.

| Checkpoint | Parameters | Warm load | Entity inference | Event inference |
| --- | ---: | ---: | ---: | ---: |
| `fastino/gliner2.5-small-v1` | 74M | 2.0 s | 1.2 s | 2.0 s |
| `fastino/gliner2.5-base-v1` | 194M | 14.7 s | 2.5 s | 3.6 s |

The Small checkpoint found exact mentions for the young lady, nurse, nursery
maid, housekeeper, and both occurrences of “under the bed.” The raw results
also contained false or competing labels, including `nursery` as an institution
and `smallpox` as a supernatural force. Preserve confidence and overlapping
labels; Qwen or later human reconciliation must not mistake mentions for a
canonical cast.

The generic structured `story_event` schema was not reliable. Both checkpoints
mixed actors, actions, targets, and evidence across nearby clauses, often at
very low field confidence. Narrower overlapping windows improved visibility of
the relevant passage but did not reliably extract “The lady … slipped down upon
the floor … hid herself under the bed” as one event. Do not feed these records
to Qwen as facts. A purpose-trained event or semantic-role model, a fine-tuned
GLiNER2 head, or Qwen constrained by exact candidate sentences remains to be
tested.

The Small checkpoint classified fifteen overlapping windows across the
chapter in about 2.3 seconds. First-person viewpoint, horror, memory, isolation,
foreboding, dialogue, description, and introspection appeared in plausible
regions. Results were still hypotheses: one window was labeled second-person
because the narrator addressed “you,” and local genre labels sometimes drifted
to historical or romance. Aggregated coverage and confidence may make this a
strong replacement for the slow Qwen-only Tags pass, but it needs a labeled
fiction test set rather than anecdotal acceptance.

## Decision

1. Continue with GLiNER2.5 Small as the default experimental mention and
   tag-candidate generator; Base did not justify its extra load time here.
2. Keep every raw exact span and classification score.
3. Do not use the generic event records as durable facts.
4. Build a Qwen audit packet that includes raw mentions plus exact sentences
   surrounding each entity/action candidate. Qwen appends corrections and
   reasons; it never overwrites specialist output.
5. Compare Chapter Reading with and without the packet on the known Carmilla
   failures before adding a visible pipeline stage.

The disposable runner is `tools/gliner_chapter_spike.py`.

## Qwen treatment experiments

The first GLiNER-assisted Qwen treatment audited 24 grouped entity candidates
and 37 tag hypotheses, then produced a per-entity chapter ledger. It completed
in 2,468.8 seconds. Entity coverage improved and the unsupported claim that the
mysterious lady “vanished” disappeared, but the Summary and Dossier still
omitted her explicit movement onto the floor and under the bed. The ledger also
assigned nearly every candidate ID to the narrator and introduced unsupported
interpretations such as the narrator learning that the visit was not a dream.
The scaffold was too broad, too expensive in generated output, and did not fix
the target action-fidelity failure.

The second treatment therefore removes all tag adjudication from Chapter
Reading, restricts entity candidates to identity-bearing labels, and adds a
small recall-oriented set of exact source passages chosen by deterministic
action cues. Qwen must audit every selected passage for grammatical actor,
literal action, and resulting state before reconciling its Summary and Dossier.
The packet contains 13 identity candidates and 16 exact passages, including
both P0050 (the needle sensation) and P0051 (the lady slips to the floor and
hides under the bed). This remains an isolated A/B experiment; it does not
write Bookinator's durable analysis artifacts.

The treatment runner is `tools/qwen_gliner_chapter_experiment.py`.

The second treatment completed in 1,875.0 seconds. Its explicit action audit
correctly recovered P0050 (the needle sensation) and P0051 (the lady starts
back, slips to the floor, and, as the narrator thinks, hides under the bed).
The unsupported “vanished” summary claim disappeared. However, the same model
still omitted P0051 from its Summary, Dossier events, and entity ledger despite
being told to reconcile every material action. It also reduced the ledger to
one entity and misattributed the servants' no-visible-mark finding to the
doctor. Better attention did not guarantee self-reconciliation.

The third experiment therefore makes reconciliation deterministic. It compares
the action audit's passage IDs with the structured evidence references actually
present in Summary, Dossier events, and ledger actions. A compact follow-up call
receives only potential gaps and existing anchored claims, explicitly accepts
or dismisses every gap, and proposes append-only additions or concrete claim
corrections. It cannot introduce evidence outside that packet. The runner is
`tools/qwen_action_repair_experiment.py`.

The targeted repair completed in 786.1 seconds, versus 1,875.0 seconds for the
full action-scaffold treatment. It restored P0051 to the Summary, Dossier event
list, and entity ledger and accepted 18 of 22 proposed target gaps. It also
demonstrated the remaining danger: the generated Summary and Dossier claims
flattened “as I thought” into an objective assertion even though the evidence
retained the qualifier. The production experiment therefore treats epistemic
language as a validation boundary. Exact deterministic action passages are now
audited during the primary read; missing Summary and Dossier coverage becomes
a compact consistency-repair packet; and Bookinator refuses an addition whose
source expresses uncertainty when the proposed claim does not.

The first bounded production rerun is capped through Carmilla Chapter I. Its
specific regression probes are P0050 (the needle sensation), P0051 (start back,
slip to the floor, and the narrator's uncertain belief about hiding under the
bed), the servants' warm-bed observation, and the later no-visible-mark claim.
