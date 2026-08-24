# Synthetic HR knowledge benchmark

Step 18 dataset version 2.0.0 is deterministic machine-authored test material. It is not a real company policy,
customer data, a human-labelled gold set, or production-quality evidence. It lives exclusively in
`tests/fixtures/synthetic_hr_knowledge`; test-support code is its only loader. Production source
catalogs, capabilities, deployment configuration, defaults, and the wheel do not reference it.
Engineering schema material under `docs/database/hr` is never ingested.

The manifest pins 16 Markdown sources, fictional UUID customers and legal entities, family-based
calibration/holdout assignments, timestamps, status, version, and a corpus digest. Ninety-six
machine-authored cases cover Arabic, English, mixed language, keyword, paraphrase, cross-language,
expected-empty, SQL-looking, prompt-injection-like, customer, module, entity, date, classification,
and conflicting-rule scenarios. Stable document IDs and section keys resolve only after the normal
adapter, ingestion, and deterministic chunking contracts succeed.

Attendance and payroll codes ending in `_fixture` are test labels, not authoritative ERP entitlement
mappings. Future, expired, and superseded examples must not be retrieved at the fixed evaluation
time. Global help has no customer owner; policies require an exact fictional customer match.

Calibration and holdout split by document family. Translations and paraphrases cannot cross the
partition boundary. Calibration alone may select a threshold. Holdout executes once after selection,
and no result may trigger tuning, winner selection, production wiring, or approval. Every threshold
remains `unapproved_test_only`.

Evaluation provenance binds dataset identity/version, corpus and partition fingerprints, active
generation, embedding profile, TEI resource policy and observed runtime identity, threshold/status,
hybrid policy, and candidate identity. Reports are aggregate-only and must exclude queries, source
content, labels, vectors, scores, authorization collections, and provider details.

Real production approval remains deferred pending authoritative documents, human judgements,
independent holdout review, zero security leaks, and an explicit signed decision. Typed contracts
cannot prove a human signature or approval-service authenticity.

## Version 1 invalidation

Version 1 was `invalidated_before_checkpoint`: lifecycle exclusions were implicit, exact-keyword
queries did not prove real anchors, positive labels were not resolved against the exact published
set, and zero-recall primary-reason diagnostics were absent. Its aborted publication attempt saw no
calibration or holdout output. Its completed result and threshold are invalid and cannot support
approval or remain active inputs. The aggregate invalidation record retains only its version,
fingerprints, defects, and approval prohibition.

## Version 2 integrity contracts

Every fixture has one immutable lifecycle decision. Precedence is `withdrawn`, `superseded`,
`future_not_effective`, `expired`, then `included`; only included fixtures reach the Markdown
adapter. Supersession is validated within customer, namespace, logical policy, and increasing
SemVer, with no missing targets, self-reference, or cycles. The immutable publication plan retains
aggregate counts for all decisions.

An exact-keyword case carries a normalized Unicode lexical anchor that is its query and occurs in
every positively labelled normalized section. Positive labels resolve only through the exact
customer-specific planned generation and the existing authorization predicate. Authorization-
negative references are stored separately and never treated as accessible relevance labels.

Zero-recall primary-reason precedence is: `provider_failure`, `incorrect_label`,
`unpublished_or_ineffective`, `authorization_filtered`, `no_lexical_match`, `below_threshold`, then
`outside_candidate_set`. Output contains aggregate counts only. Queries, anchors, content, labels,
scores, vectors, customer context, and authorization collections remain test-internal and outside
public/model/audit contracts.

Version 2 uses a new fixed partition salt and explicit family assignments. Both partitions cover
Arabic, English, mixed language, product documentation, customer policy, both fictional customers,
and negative cases. Calibration alone selects the test-only threshold; observed holdout metrics may
not cause dataset edits or tuning.

## Completed version 2 evaluation

The one allowed version 2 holdout execution used the calibration-selected threshold
`0.8102476411910277` with status `unapproved_test_only`. This value is an evaluation result only: it
is not a runtime default, production threshold, retrieval-candidate selection, or approval.

Expected-empty accuracy was 100%, and the evaluation reported zero authorization leaks,
cross-customer leaks, forbidden-reference exposures, and provider failures. Hybrid retrieval reduced
some aggregate zero-recall cases relative to semantic retrieval, but semantic and hybrid quality
remain insufficient for production and neither candidate is approved or promoted. Zero-recall
diagnostics retain aggregate reason counts only.

The corpus and labels remain machine-authored synthetic regression material. Production approval
still requires real approved documents and independently human-labelled relevance judgements. The
completed holdout metrics must not be used to tune version 2; any dataset, label, policy, model, or
runtime change requires a new version, new fingerprints, and a new independently controlled run.
