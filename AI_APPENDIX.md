# StockFlow AI Usage Appendix

## 1. Purpose of this appendix

This appendix explains how AI assistance fit into the StockFlow development
process, which architecture decisions were most important, what implementation
defects were found during review, and how the resulting code was verified. It is
written for technical review and interview discussion rather than as a claim
that the project was generated automatically.

The evidence used for this document is limited to the current repository:

- `AGENTS.md`, which defines the architecture, phasing, business rules, and
  verification expectations given to an AI coding agent
- `README.md`, which explicitly states that AI assistance was used
- Git history and commit diffs
- the current application code, migrations, and test suite
- verification commands executed while preparing this appendix

`PROMPTS.md`, `AI_NOTES.md`, and a previous `AI_APPENDIX.md` are not present in
the repository. Original chat transcripts and historical command output are
also not tracked. Where that evidence is unavailable, this appendix says so
instead of reconstructing it from memory.

## 2. AI tools and models used

The repository confirms that an AI assistant was used, but the specific AI
product, provider, model name, model version, and client are **not documented in
repository notes**. It would therefore be inaccurate to name a particular model
or claim that one model produced a specific file.

The tracked evidence does show the operating framework used with the assistant:

- `AGENTS.md` gave the assistant explicit responsibility boundaries for models,
  serializers, forms, services, selectors, views, tasks, templates, permissions,
  and audit helpers.
- It required PostgreSQL, transaction-safe inventory operations, scoped HTMX,
  automated tests, migration review, and command verification.
- Git commits are authored by the developer, which preserves developer
  ownership even though AI assistance was part of the workflow.
- StockFlow has no AI dependency at runtime and does not call an AI API.

## 3. Development workflow with AI

The Git history supports a phased, reviewable workflow rather than a single
large generated change:

1. Establish project rules and structure (`a6e8a6d`, `894dde3`).
2. Configure PostgreSQL and environment handling (`801d078`).
3. Add domain models and migrations (`ec3c012`).
4. Add the atomic reservation service and focused tests (`a74055b`).
5. Add transitions, expiration, inventory adjustments, audit logging, API,
   idempotency, reports, permissions, browser pages, and HTMX in separate
   commits.
6. Add broader constraint, concurrency, and query-performance tests
   (`ea646d9`, `3180407`).
7. Perform a dedicated hardening pass for workflow bypasses, idempotency,
   Celery failure isolation, pagination/schema accuracy, database state checks,
   browser visibility, and production settings (`ba46a93` through `86379f7`).

This sequence is consistent with the process in `AGENTS.md`: inspect the current
code, keep business logic in services, implement only the active phase, add
focused tests, run checks, and review the diff. The repository does not preserve
the exact back-and-forth conversation with the AI or identify which individual
lines began as AI suggestions.

## 4. The two most important architectural prompts

The original prompt file is not tracked, so the prompt wording cannot be quoted
verbatim. Based on the prompt labels supplied for this appendix and the matching
Git commits, the two strongest architecture anchors are:

### Prompt 3 - Core Models and PostgreSQL Constraints

Evidence: commit `ec3c012` added the Product, Warehouse, Inventory, Order,
OrderItem, and StockMovement models plus their initial migrations. The current
models and later state-constraint commit `3cb8c81` show that database integrity
remained an explicit architectural concern.

The design established:

- unique SKU and warehouse code
- one Inventory row per product/warehouse pair
- one OrderItem per order/product/warehouse combination
- positive prices and item quantities
- nonnegative inventory and `reserved_quantity <= quantity`
- decimal money fields and order-item price snapshots
- calculated, rather than stored, available quantity
- indexed fields for common lookups and expiration selection
- database checks for finite state values added during the later hardening pass

### Prompt 5 - Atomic Order Reservation Service

Evidence: commit `a74055b` added `apps/orders/services.py`, domain exceptions,
and `tests/test_order_reservation_service.py`.

The design established:

- a dedicated `reserve_order()` service instead of workflow logic in a ViewSet
  or serializer
- one `transaction.atomic()` boundary
- `select_for_update()` on the order and affected inventory rows
- deterministic product/warehouse lock ordering
- validation of all items before any inventory mutation
- rollback of inventory, movement, item-price, and order changes together
- current Product price snapshots and Decimal subtotal/total calculations
- structured domain exceptions for invalid transitions, missing inventory,
  inactive catalog data, invalid quantities, and insufficient stock

## 5. Why those prompts mattered

The model prompt defined what states are representable. That matters because
service code is not the only possible database writer: migrations, admin tools,
scripts, and direct SQL can bypass serializer or form validation. Uniqueness and
check constraints make key invariants durable at the persistence boundary. The
later `3cb8c81` hardening commit is also a useful lesson: Django `choices` improve
application validation but do not themselves create PostgreSQL CHECK
constraints.

The reservation prompt defined how state changes safely under concurrency.
`transaction.atomic()` provides all-or-nothing behavior, but it does not by
itself serialize two requests reading the same available stock. Row locks are
needed to prevent competing reservations from both succeeding. Deterministic
locking reduces inconsistent lock order across multi-item orders, and validating
every item before writing prevents partial reservation when one row is missing
or insufficient.

The service boundary also made later work possible without copying rules. The
API and browser views call the same order services, cancellation is reused by
Celery expiration, audit records were added inside existing transactions, and
tests exercise the domain operations directly.

## 6. AI-generated or AI-suggested mistakes I identified

The repository does not attribute individual defects to AI-authored versus
human-authored lines. The examples below are therefore described precisely as
**implementation mistakes found during review of an AI-assisted project**. Git
history proves that the earlier behavior existed and that it was corrected; it
does not prove sole AI authorship or preserve the exact reviewer conversation.

Three confirmed examples are used:

### Example A - Incomplete reservation idempotency transaction

**Context:** Reservation idempotency was introduced in commit `62fb280` and
hardened in commit `2e1a1c1`.

### Example B - One expiration failure could stop a batch

**Context:** Reservation expiration was introduced in commit `7230e5a` and
refactored for failure isolation in commit `ee23ffd`.

### Example C - Empty orders could pass reservation

**Context:** The original reservation service in `a74055b` validated the items
that existed but did not require at least one item. Commit `ba46a93` added the
missing domain rule.

Other review fixes are also visible in Git history, including admin workflow
blocking, disabled undesigned PUT operations, spreadsheet-safe CSV text,
inventory-movement pagination and schema correction, and database checks for
finite state fields. The three examples above were selected because they most
directly illustrate transaction boundaries, task failure boundaries, and domain
edge-case validation.

## 7. What AI suggested

The exact AI messages are **not documented in repository notes**, so this
section does not invent quotations. The evidence-supported earlier
implementations were:

### Example A - Earlier idempotency implementation

The earlier reserve API acquired an IdempotencyRecord, called `reserve_order()`,
and then completed the record in separate steps in the view. `reserve_order()`
had its own transaction, so reservation side effects could commit before the
idempotency response record was completed. The acquisition path did not enforce
`expires_at`, and a FAILED record fell through to the same response used for an
in-progress record.

### Example B - Earlier expiration implementation

The earlier periodic task selected eligible IDs and called `cancel_order()`
directly inside one Python loop. It caught `InvalidOrderTransition`, but an
unexpected exception for one order escaped the loop before later IDs were
attempted.

### Example C - Earlier empty-order behavior

The earlier reservation service loaded an order's items and validated item
quantities, active products, active warehouses, inventory existence, and stock.
For an empty list, each validation passed vacuously. The service could therefore
set a draft order to reserved with a zero total and no reservation movements.

## 8. Why it was wrong

### Example A - Idempotency risk

Idempotency is a correctness boundary, not only response caching. If reservation
committed and completion of the idempotency record then failed, the same key
could remain IN_PROGRESS without a replayable response. A stale record could
block the key indefinitely, while retry semantics for FAILED records were not
defined clearly. This made crash recovery and duplicate-request behavior
incomplete even though the reservation service itself remained atomic.

### Example B - Expiration isolation risk

A permanently failing old reservation could repeatedly prevent newer eligible
reservations later in the selected batch from being processed. Retrying the
single batch would repeat the same ordering problem. Transient database or lock
failures also had no bounded per-order retry policy.

### Example C - Invalid domain transition

An order with no items has nothing to reserve. Marking it reserved creates a
state that satisfies the status transition mechanically but violates the
business meaning of reservation. It also produces no stock movement, which
makes the resulting state difficult to explain operationally.

## 9. How I detected the problem

The repository does not include review meeting notes or historical failing test
output, so it does not document the exact human/AI discovery conversation. The
detection evidence is the focused fix history and the regression tests added
with each correction.

### Example A - Detection evidence

The `2e1a1c1` diff moved orchestration out of the view and added tests including:

- `test_completion_failure_rolls_back_reservation_and_idempotency_record`
- `test_stale_in_progress_record_is_reclaimed_and_reservation_completes`
- `test_stale_in_progress_record_does_not_repeat_legacy_reservation_side_effects`
- `test_unexpired_failed_record_is_rejected_without_retry`
- `test_expired_failed_record_is_reclaimed_and_retried`
- `test_concurrent_duplicate_requests_do_not_reserve_twice`

These tests identify the missing failure states directly: completion failure,
stale leases, FAILED behavior, legacy side effects, and real concurrent duplicate
requests.

### Example B - Detection evidence

The `ee23ffd` diff added explicit tests that a dispatcher attempts later orders
before reporting a dispatch failure and that an unexpected per-order failure does
not prevent another order from expiring. It also added a test for bounded retry
on `OperationalError` and `InterfaceError`.

### Example C - Detection evidence

The `ba46a93` diff added focused service, API, and browser tests:

- `test_empty_order_cannot_be_reserved`
- `test_empty_order_reservation_returns_conflict_without_domain_changes`
- `test_empty_order_reservation_error_is_displayed`

The tests assert that status and `reserved_at` remain unchanged and that no
StockMovement or AuditLog is written.

## 10. How I corrected it

### Example A - Idempotency correction

Commit `2e1a1c1` introduced `execute_idempotent_reservation()`, placing record
acquisition, reservation execution, and response completion inside one outer
`transaction.atomic()` boundary. Existing records are locked with
`select_for_update()`. New processing ownership receives a five-minute lease;
completed responses receive 30-day retention. Expired IN_PROGRESS or FAILED
records can be reclaimed, while unexpired FAILED records return a distinct
conflict. A bounded cleanup helper was added for expired records.

The completion-failure regression test deliberately makes the final record save
raise and verifies that the order, inventory reservation, movement, audit log,
and newly created idempotency record all roll back.

### Example B - Expiration correction

Commit `ee23ffd` split the workflow into:

- a bounded dispatcher, `expire_reserved_orders`, which queues one task per
  eligible order and continues attempting later dispatches
- an idempotent per-order task, `expire_reserved_order`, which rechecks
  eligibility and calls the existing cancellation service

The per-order task skips non-reserved states, remains duplicate-safe through the
locked cancellation transition, and automatically retries transient Django
database `OperationalError` and `InterfaceError` failures with backoff, jitter,
and a maximum of three retries. Unexpected bugs still fail visibly instead of
being silently swallowed.

### Example C - Empty-order correction

Commit `ba46a93` added the `EmptyOrder` domain exception and
`_validate_order_has_items()` immediately after loading the locked order's
items. The API maps the exception to a structured conflict response, and the
browser displays the domain error without bypassing the service.

## 11. How AI-generated code was verified

The repository uses several verification layers rather than relying on AI
explanations:

- **Database constraints:** `tests/test_database_constraints.py` writes invalid
  states through the ORM and expects PostgreSQL `IntegrityError`.
- **Service behavior:** reservation, transition, adjustment, and audit tests
  inspect all affected rows after success and failure.
- **Rollback injection:** tests monkeypatch movement, audit, or idempotency writes
  to fail and then assert that the complete transaction rolled back.
- **Real concurrency:** reservation and idempotency tests use
  `pytest.mark.django_db(transaction=True)`, separate database connections,
  `ThreadPoolExecutor`, and synchronization where needed. Sequential tests are
  not presented as concurrency proof.
- **Task safety:** expiration tests cover eligibility, duplicate execution,
  failure isolation, retry configuration, batch bounds, and audit/movement
  duplication.
- **HTTP boundaries:** API, permission, browser, HTMX, CSRF, and OpenAPI tests
  verify that views call services and enforce authentication and roles.
- **Query behavior:** query-count tests and SQL-oriented selector tests cover
  N+1 and database-side filtering risks.

The following commands were run while preparing this appendix. Their exact
results were:

```text
.venv\Scripts\python.exe manage.py check
System check identified no issues (0 silenced).

.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
No changes detected.

.venv\Scripts\python.exe -m pytest -q
194 passed, 40 warnings in 40.07s.

git diff --check
Passed with no whitespace errors.
```

The 40 pytest warnings came from drf-spectacular's use of Python's deprecated
`_UnionGenericAlias` compatibility type in the idempotency, low-stock report,
and OpenAPI tests. They did not represent test failures.

Historical commits contain the tests but not their original command output or
pass counts. Current command results should not be misrepresented as archived
results from an earlier development phase.

## 12. Limitations of the AI workflow

- The AI product and model are not recorded, so model-specific performance or
  attribution cannot be evaluated.
- The original prompt transcript is not tracked. Prompt names in this appendix
  are linked to matching Git commits, but the full wording and intermediate AI
  responses are unavailable.
- Git proves what changed, not whether a particular line was first written by
  the developer or suggested by AI.
- Historical test output and review discussions are not stored. Only the current
  verification run and test source can be reported exactly.
- AI-assisted code can look locally correct while missing a larger failure
  boundary. The idempotency and expiration examples both required reasoning
  across multiple transactions or multiple jobs.
- Framework defaults require independent review. Examples in the hardening
  history include ModelViewSet PUT exposure, editable admin workflows, and
  model choices without database CHECK constraints.
- Edge cases need explicit tests. Empty orders and spreadsheet formula prefixes
  were not protected until the later review pass.

Candidate mistakes considered but not presented as confirmed AI mistakes:

- A wrong model import or wrong model location assumption is **not documented in
  repository notes**.
- Use of `price` instead of `unit_price` is **not documented in repository
  notes**.
- Commit `3180407` proves that query performance was improved, but the repository
  does not document an AI-specific N+1 claim or a failing query-count result, so
  it is not attributed as an AI mistake here.
- Commit `86379f7` proves that production settings were hardened, but a specific
  AI-caused Docker/local-environment confusion is **not documented in repository
  notes**.

## 13. What I learned

The main lesson is that the most valuable prompts define invariants and failure
boundaries, not just files to generate. Prompting for models with explicit
database constraints made the persistence rules reviewable. Prompting for an
atomic reservation service forced transaction, lock ordering, validation order,
and rollback behavior to be discussed together.

I also learned to separate confidence from evidence. A plausible implementation
is not enough for concurrency, idempotency, retries, or permissions. Those areas
need adversarial tests: two simultaneous requests, a failed final write, a stale
processing record, one bad task in a batch, a direct database write, or a route
method supplied by framework defaults.

Finally, AI is most useful here as a collaborator for implementation and review,
while the developer remains responsible for architecture, scope, evidence,
tests, and accepting or rejecting the output.

## 14. Interview-ready summary

I used AI assistance within a deliberately constrained engineering workflow.
The two most important architecture decisions were putting durable invariants in
PostgreSQL-backed models and putting reservation in a dedicated atomic service
with deterministic row locking. I did not treat the first implementation as
finished: later review found cross-boundary issues in idempotency, Celery batch
failure handling, and the empty-order edge case. I corrected those issues with
smaller transaction and task boundaries, explicit domain errors, and regression
tests, including real PostgreSQL concurrency tests. The repository does not
record the AI model or line-level authorship, so I describe AI as an assistant,
not as the owner or sole author of the project.
