# Model tool-interaction transcript contract

The provider-neutral orchestration boundary retains an immutable ordered transcript of completed
model tool interactions. The earlier contract retained only public tool-result messages. That was
insufficient to reconstruct the standard chat-completions continuation because the original
assistant call, exact argument JSON, and call/result adjacency had been discarded.

Each `ModelToolInteraction` contains one `ModelToolCall` immediately paired with one
`ToolResultMessage`. The call retains its call ID, tool name, version, exact provider-supplied JSON
string, and a recursively immutable parsed object. The result retains the established
`untrusted_tool_result` marker. Call IDs, tool identities, and versions must match across the pair.
The `ModelTurnRequest.interactions` tuple preserves original execution order and rejects duplicate
call IDs, orphan results, and invalid constructed objects.

## Argument preservation and validation

Live adapters must construct calls from the exact serialized argument string. It is preserved
byte-for-byte without whitespace, key-order, or Unicode normalization. Parsing accepts exactly one
JSON object, rejects duplicate keys at every depth, rejects non-finite or non-interoperable numbers,
and enforces the existing 16 KiB, depth-ten, and 512-node ceilings. The parsed projection must be
exactly equivalent to the raw JSON and is recursively frozen. Test providers use a separate
deterministic constructor that emits compact, key-sorted UTF-8 JSON.

Equivalence is JSON-type-sensitive: booleans are not integers, integers are not floating-point
numbers, and positive and negative floating-point zero remain distinct. Unicode escapes and their
decoded scalar values are equivalent while the original escape spelling remains unchanged in the
raw string. Sensitive model validation errors suppress input values rather than relying only on
`repr=False`.

The orchestrator defensively rebuilds every returned call from its raw JSON before gateway access.
It applies any stricter configured argument budget, invokes the read gateway once, pairs the public
result once, and appends without sorting or rewriting. Before every provider turn it independently
revalidates all pairs and recomputes interaction count, every raw argument byte/depth/node budget,
total call count, and accumulated serialized public-result bytes. It does not trust incremental
counters or validation performed before an object was constructed. Replaying the transcript to a
later model turn does not execute the gateway again.

## Privacy and provider neutrality

The transcript is internal model-adapter input and is hidden from default representations. Raw and
parsed arguments, public tool-result payloads, call IDs, selected business identifiers, and queries
must not enter public chat results or agent/tool audit events. The transcript contains no trusted
request context, authorization collections, internal denials, audit records, runtime metadata, or
provider credentials.

The contract can reconstruct an assistant message containing one tool call followed immediately by
its matching tool-result message. It contains no OpenRouter, OpenAI, or other provider-specific
fields.

## Deferred reasoning continuation

Reasoning text, `reasoning_details`, encrypted or opaque continuation state, previous response IDs,
and mutable provider-side call maps are intentionally excluded. A future Ox Alpha synthetic live
compatibility test must determine whether ordinary assistant-call/tool-result replay works without
reasoning state. If the model requires reasoning-state replay, that requires a separate explicit
provider-neutral contract and privacy decision.
