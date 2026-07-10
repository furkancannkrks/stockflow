# AGENTS.md

## Project Overview

StockFlow is a backend-focused inventory and order reservation management
system developed as an internship case project.

The application must provide:

- A browser-based internal interface
- REST API endpoints
- PostgreSQL persistence
- Product and warehouse management
- Inventory tracking
- Order reservation, confirmation, cancellation, and shipping
- Stock movement history
- Authentication and role-based permissions
- Swagger/OpenAPI documentation
- Automated tests
- Background reservation expiration
- Idempotent reservation requests
- Low-stock CSV reporting
- Audit logging
- HTMX enhancements in a dedicated phase

## Technology Stack

- Python
- Django
- Django REST Framework
- PostgreSQL
- Django ORM
- Django Templates
- Bootstrap
- HTMX for explicitly scoped enhancement tasks only
- django-filter
- pytest and pytest-django
- drf-spectacular
- Celery
- Redis
- Celery Beat
- Docker and Docker Compose

Do not introduce React, Vue, or another frontend framework unless explicitly
requested.

## Core Architecture

Keep responsibilities separated:

- Models define database structure and model-level invariants.
- Serializers validate API input and shape API output.
- Forms validate browser-submitted data.
- Services contain business operations and state changes.
- Selectors contain reusable read/query logic.
- Views and ViewSets coordinate HTTP requests and responses.
- Templates render the internal browser interface.
- Celery tasks locate eligible records and call existing services.
- Permission classes and decorators enforce authorization.
- Audit helpers create explicit audit records inside business transactions.

Do not place complex stock reservation, inventory adjustment, audit, expiration,
or order transition logic directly inside views, templates, serializers, forms,
signals, or Celery tasks.

## Implementation Phasing

AGENTS.md describes the target architecture of the completed project.

However, features must be implemented only during their dedicated prompts.

Rules:

- Do not implement a later-phase feature early merely because it appears in
the final architecture.
- Do not create placeholder models, services, tasks, or dependencies for a
feature that has not reached its dedicated prompt.
- The current prompt defines the active implementation scope.
- Later prompts may retrofit completed services without replacing their core
domain behavior.
- When a final-state rule depends on a feature that does not exist yet, defer
that rule until the feature's dedicated prompt.

## Recommended Project Structure

```text
stockflow/
├── AGENTS.md
├── PROMPTS.md
├── README.md
├── AI_APPENDIX.md
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── manage.py
├── config/
├── apps/
│   ├── users/
│   ├── products/
│   ├── inventory/
│   ├── orders/
│   ├── audit/
│   └── reports/
├── templates/
├── static/
└── tests/
```

This structure is a guideline. Do not create an app only for appearance if the
existing repository has a simpler and coherent organization.

## Database Rules

- PostgreSQL is the primary database.
- Do not switch the project to SQLite.
- Use `DecimalField` for monetary values.
- Use database constraints where appropriate.
- Add indexes for frequently filtered fields.
- Prevent duplicate Product SKU values.
- Prevent duplicate Warehouse code values.
- Prevent duplicate Inventory records for the same product and warehouse.
- Prevent duplicate product and warehouse combinations inside one order.
- Prevent negative `quantity` and `reserved_quantity` values.
- `reserved_quantity` must never exceed `quantity`.
- Do not store `available_quantity` as an independent database field.
- Review all generated migrations before applying them.
- Do not edit historical migrations without a clear reason.

## Core Domain Models

The project includes these main domain concepts:

- Product
- Warehouse
- Inventory
- Order
- OrderItem
- StockMovement
- AuditLog
- IdempotencyRecord
- Custom User

Use readable `related_name` values and meaningful `__str__` methods.

## Inventory Rules

Available stock is calculated as:

```text
available_quantity = quantity - reserved_quantity
```

Never store `available_quantity` as an independent database field.

A stock reservation must:

1. Run inside `transaction.atomic()`.
2. Lock affected Inventory rows with `select_for_update()`.
3. Lock rows in a deterministic order where practical.
4. Validate all order items before modifying any inventory row.
5. Roll back the complete transaction if one item fails.
6. Create required StockMovement records in the same transaction.
7. Never decrease physical quantity during reservation.

A stock adjustment must:

1. Run inside `transaction.atomic()`.
2. Lock the affected Inventory row.
3. Protect already reserved stock.
4. Create a StockMovement record.
5. Roll back all changes together if validation fails.

## Order Status Rules

Allowed transitions:

- `draft -> reserved`
- `reserved -> confirmed`
- `reserved -> cancelled`
- `confirmed -> shipped`

Reject all other transitions.

When reserving:

- Increase `reserved_quantity`.
- Keep physical `quantity` unchanged.
- Create reservation StockMovement records.

When confirming:

- Decrease `quantity`.
- Decrease `reserved_quantity`.
- Create `stock_out` StockMovement records.

When cancelling a reserved order:

- Decrease `reserved_quantity`.
- Keep physical `quantity` unchanged.
- Create `reservation_release` StockMovement records.

When shipping:

- Change status only.
- Do not decrease inventory again.

## Reservation Expiration State Decision

Expired reservations transition from `reserved` to `cancelled`.

The project does not use a separate `expired` Order status.

The expiration source is distinguished through:

- A `reservation_release` StockMovement
- A cancellation source value of `expiration`
- An `order_cancelled` AuditLog record whose metadata contains:
  `"source": "expiration"`

Manual cancellation uses:

- The same `reserved -> cancelled` status transition
- A cancellation source value of `manual`

Expiration must reuse the existing cancellation service and must not implement
a second reservation-release workflow.

## Domain Exceptions

Use clear domain-specific exceptions where appropriate, such as:

- `InvalidOrderTransition`
- `InsufficientStock`
- `InactiveProduct`
- `InactiveWarehouse`
- `InventoryNotFound`
- `InvalidInventoryAdjustment`
- `DuplicateOrderItem`
- `IdempotencyConflict`
- `IdempotencyInProgress`
- `IdempotentReplay`
- `ReservationAlreadyExpired`

`IdempotentReplay` does not have to be an exception if a structured service
result provides a clearer design.

Do not use broad `except Exception` blocks unless handling a true boundary and
re-raising or logging appropriately.

## API Rules

- Use Django REST Framework.
- Use server-side filtering, searching, ordering, and pagination.
- Do not fetch all records and filter them in Python.
- Do not trust product prices, subtotals, totals, or statuses sent by clients.
- Read the current `Product.unit_price` from the database.
- Use consistent API error response structures.
- Map domain exceptions to suitable HTTP responses.
- Document endpoints with OpenAPI/Swagger.
- Use POST requests for state-changing custom actions.
- Keep API views thin and delegate workflows to services.
- Apply permissions on the server, not only in the interface.

Preferred error structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": []
  }
}
```

## Browser Interface

The project must have its own browser interface in addition to Django Admin.

Required pages:

- Login
- Dashboard
- Product list, detail, create, and update
- Warehouse list
- Inventory list and detail
- Stock adjustment form
- Order list, create, detail, and draft update
- Stock movement list
- Audit log inspection where appropriate
- Low-stock CSV download entry point

Core pages must use:

- Django Templates
- Bootstrap
- Full-page server rendering
- Standard form POST requests
- Redirect-after-POST behavior

Django Admin is a supporting management interface, not the main project UI.

## HTMX Scope

Core browser interface work in Prompts 11–13 uses plain Django Templates,
Bootstrap, full-page rendering, standard form POSTs, and redirects.

HTMX is introduced only during the dedicated Bonus 5 enhancement pass.

Allowed HTMX enhancement examples include:

- Updating a stock adjustment result without reloading the full page
- Refreshing dashboard summary cards
- Refreshing recent stock movements
- Updating an order status and action section
- Loading a small server-rendered partial

Do not introduce HTMX into core browser pages unless a specific prompt
explicitly scopes the interaction.

Do not replace the REST API or service layer with HTMX-specific business logic.

HTMX endpoints must:

- Reuse existing services
- Enforce the same authentication and permissions
- Enforce CSRF protection
- Return server-rendered partial templates
- Preserve a reasonable non-HTMX fallback
- Avoid duplicating full-page and partial-page business logic

## Bonus Features

The following bonus features are required for this project:

- Reservation expiration using Celery, Redis, and Celery Beat
- Idempotency-Key support for order reservation
- CSV export of low-stock products
- Audit logging for:
  - Product updates
  - Inventory adjustments
  - Order reservations
  - Order cancellations
  - Order confirmations
- HTMX-enhanced browser interactions in a dedicated pass

Bonus features must follow the same architecture discipline as core features.

They must:

- Reuse the service layer
- Preserve transaction boundaries
- Enforce authentication and permissions
- Include automated tests
- Avoid duplicated business logic
- Use PostgreSQL-compatible persistence
- Be documented in README and OpenAPI where applicable
- Define failure, retry, duplicate request, authorization, and rollback behavior

## Background Tasks

Celery is used for asynchronous and scheduled workflows.

Redis is used as the Celery broker and result backend unless the implementation
documents another approved design.

Celery Beat schedules reservation expiration checks.

Background tasks must not contain independent copies of domain logic.

Tasks should:

- Locate eligible records efficiently
- Call existing service functions
- Handle expected domain exceptions
- Be safe to retry
- Avoid processing the same order twice
- Record useful failure information
- Avoid broad exception swallowing
- Process records in controlled batches where appropriate

The reservation expiration task must reuse cancellation or reservation-release
service behavior.

Do not update `reserved_quantity` directly inside a Celery task if the same
operation already exists in a service.

A task retry must not release the same reservation more than once.

## Reservation Expiration Rules

A reserved order expires when it remains unconfirmed for 30 minutes.

The implementation must define and document:

- Which timestamp starts the expiration window
- Whether expiration maps to `cancelled` or a dedicated `expired` state
- How duplicate task execution is prevented
- How retries behave
- How orders are rechecked after row locking
- How StockMovement and AuditLog duplication is prevented

Use timezone-aware datetime values.

Expiration must:

- Release reserved inventory
- Keep physical quantity unchanged
- Create reservation-release movements once
- Create an audit record once
- Remain safe under retries and concurrent workers

## Idempotency Rules

The order reservation API supports an `Idempotency-Key` request header.

Idempotency must be persisted in PostgreSQL.

The implementation must define:

- User or client scope
- Endpoint or operation scope
- Order scope
- Request fingerprint
- Processing state
- Stored response status
- Stored response body
- Retention or expiration behavior

Rules:

- Repeating the same key with the same logical request must not reserve twice.
- A completed request should replay the original response.
- Reusing the same key with a different order or payload must be rejected.
- An in-progress duplicate must not start a second reservation.
- Idempotency records must be created and updated safely under concurrency.
- Failed-request replay behavior must be documented.
- Idempotency must not replace normal transaction and row-locking protections.
- Do not rely on Redis alone for permanent idempotency correctness.

## Audit Logging

Audit logging is separate from StockMovement history.

- StockMovement records how inventory changed.
- AuditLog records who performed an important action and what object changed.

Required audited actions:

- `product_updated`
- `inventory_adjusted`
- `order_reserved`
- `order_cancelled`
- `order_confirmed`

An audit record should include where appropriate:

- Actor
- Action
- Target model
- Target object identifier
- Human-readable target representation
- Structured metadata
- Correlation or idempotency information
- Created timestamp

Audit logging must:

- Be performed inside the same transaction as the successful domain operation
- Never record success when the domain transaction rolls back
- Avoid passwords, secrets, or unnecessary personal data
- Use structured JSON metadata for useful before-and-after information
- Be created explicitly by services where domain context exists
- Avoid generic signals when the actor or context would be unreliable
- Be read-only through normal application interfaces

Do not use AuditLog as a replacement for StockMovement.

## Audit Logging Phase

Audit logging is introduced in Prompt 7.5.

Before Prompt 7.5:

- Reservation, confirmation, cancellation, product update, and inventory
  adjustment services must not depend on an AuditLog model.
- Do not create placeholder AuditLog models or incomplete audit helpers.
- Core workflows must remain fully functional without audit logging.

During Prompt 7.5:

- Retrofit the existing reserve_order, confirm_order, cancel_order,
  adjust_inventory, and product update workflows.
- Audit records must be added inside the existing transaction boundaries.
- Existing domain behavior must not be rewritten or duplicated.
- Failed or rolled-back operations must not leave audit records.

## Reports

The low-stock CSV report must reuse the same low-stock definition used by the
application:

```text
available_quantity <= low_stock_threshold
```

Requirements:

- Query in PostgreSQL
- Reuse selectors or querysets
- Avoid duplicate low-stock calculations
- Use Python's `csv` module
- Escape values correctly
- Use `StreamingHttpResponse` when appropriate
- Enforce authentication and permissions
- Avoid N+1 queries
- Document the endpoint in OpenAPI

## Authentication and Permissions

Use a custom User model from the beginning.

Required roles:

- `manager`
- `warehouse_staff`

Permissions must be enforced for both API and browser views.

Do not rely only on hiding buttons in templates.

Unauthorized actions return 403.

Document which role may:

- Create and update products
- Create and update warehouses
- View inventory
- Adjust stock
- View orders
- Reserve, confirm, cancel, and ship orders
- Export reports
- View audit information

## Query Performance

Consider:

- `select_related()`
- `prefetch_related()`
- `aggregate()`
- `annotate()`
- `Exists()`
- `F()` expressions
- `Q()` objects
- Database indexes

Avoid:

- N+1 queries
- Queries inside loops
- Repeated aggregate queries
- Python-side filtering
- Unbounded pagination
- Blind prefetching

Do not optimize blindly. Explain the expected benefit of each optimization.

## Testing Requirements

Use pytest and pytest-django.

After changing business logic, run the relevant test selection, then the full
suite when practical.

Important test areas:

- Unique Product SKU
- Unique Warehouse code
- Inventory uniqueness
- Negative stock prevention
- `reserved_quantity <= quantity`
- Available quantity calculation
- Successful reservation
- Insufficient stock conflict
- Atomic rollback
- Real concurrency behavior where claimed
- Inactive product rejection
- Inactive warehouse rejection
- Successful confirmation
- Successful cancellation
- Successful shipping
- Invalid transitions
- Stock adjustment protection
- StockMovement creation
- AuditLog creation and rollback behavior
- Reservation expiration and retry safety
- Idempotency replay and conflict behavior
- Duplicate reservation prevention
- Product and order filtering
- Pagination
- Permissions
- Low-stock CSV correctness
- HTMX partial responses
- Non-HTMX fallback
- CSRF enforcement

A feature is not complete while its relevant tests fail.

Do not claim concurrency safety based only on sequential tests.

## Migrations

After model changes:

```bash
python manage.py makemigrations
python manage.py migrate
```

Rules:

- Review generated migrations.
- Do not delete or rewrite existing migrations without a clear reason.
- Do not claim migrations work without running them.
- Prefer additive, reviewable migrations.
- Include constraints and indexes explicitly where required.

## Docker

The main `docker-compose.yml` must include:

- `web`
- `db`
- `redis`
- `celery_worker`
- `celery_beat`

Do not postpone Redis and Celery to an optional Compose file because reservation
expiration is in scope.

Docker requirements:

- PostgreSQL data uses a named volume.
- Redis is reachable by Django and Celery services.
- `web`, `celery_worker`, and `celery_beat` share the same application image
  where practical.
- Environment variables are shared safely.
- Real secrets are not committed.
- PostgreSQL and Redis include health checks where appropriate.
- The web service does not run destructive commands automatically.
- Seed data is not run automatically on every startup.
- Exactly one Beat scheduler instance runs.
- Celery tasks are discoverable from the Django project.
- Container commands are documented.

Expected verification commands:

```bash
docker compose config
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_data
docker compose exec web pytest
docker compose logs celery_worker
docker compose logs celery_beat
```

## Code Quality

- Prefer small and focused functions.
- Add type hints where useful.
- Avoid unnecessary abstractions.
- Avoid duplicated business logic.
- Use clear domain-specific names.
- Do not leave commented-out code.
- Do not silently ignore errors.
- Do not install a dependency without explaining why it is needed.
- Do not rewrite unrelated files.
- Keep public behavior stable unless a change is intentional and tested.
- Use timezone-aware datetimes.
- Use Decimal arithmetic for money.

## Work Process

Before implementing a multi-file feature:

1. Read AGENTS.md.
2. Inspect the existing repository.
3. Explain the current data flow.
4. Identify affected files.
5. Identify business rules.
6. Identify transaction and locking boundaries.
7. Identify validation and permission requirements.
8. Identify tests to add.
9. Implement the smallest complete version.
10. Run relevant tests.
11. Run Django system checks.
12. Review migrations when present.
13. Review the diff for unrelated changes.
14. Summarize changed files, commands, results, and limitations.

Do not claim success for a command that was not executed.

Environment note: this project is developed on Windows. Use `py -3` instead of
`python` for all management commands (e.g. `py -3 manage.py migrate`).

## AI Appendix

Keep notes throughout development about:

- Important prompts
- Architectural decisions influenced by AI
- AI-generated errors detected by the developer
- How those errors were identified
- How those errors were corrected
- Commands and tests used for verification

These notes will later be transferred to `AI_APPENDIX.md`.

Do not invent prompts, errors, tools, decisions, or verification results.

