# Entity-relationship diagram

22 tables in three schemas: `app` (operational data), `report` (views) and `audit` (history).
Every column, type and constraint is listed in the [data dictionary](data_dictionary.md).

```mermaid
erDiagram
    USERS ||--o{ ORG_MEMBERS : "works for"
    ORGANIZATIONS ||--o{ ORG_MEMBERS : "has staff"
    ORGANIZATIONS ||--o{ EVENTS : hosts
    VENUES ||--o{ ROOMS : contains
    VENUES ||--o{ EVENTS : "takes place at"
    EVENT_CATEGORIES ||--o{ EVENTS : classifies
    EVENT_CATEGORIES |o--o{ EVENT_CATEGORIES : "parent of"
    EVENTS ||--o{ SESSIONS : "agenda"
    ROOMS ||--o{ SESSIONS : "booked for"
    SESSIONS ||--o{ SESSION_SPEAKERS : ""
    SPEAKERS ||--o{ SESSION_SPEAKERS : presents
    EVENTS ||--o{ TICKET_TYPES : sells
    EVENTS ||--o{ PROMO_CODES : offers
    USERS ||--o{ ORDERS : places
    EVENTS ||--o{ ORDERS : "for"
    PROMO_CODES |o--o{ ORDERS : "applied to"
    ORDERS ||--|{ ORDER_ITEMS : contains
    TICKET_TYPES ||--o{ ORDER_ITEMS : "sold as"
    ORDER_ITEMS ||--|{ TICKETS : issues
    ORDERS ||--o{ PAYMENTS : "paid by"
    PAYMENTS ||--o{ REFUNDS : "returned by"
    TICKETS ||--o| CHECK_INS : "used at door"
    TICKET_TYPES ||--o{ WAITLIST : "queue for"
    USERS ||--o{ WAITLIST : joins
    USERS ||--o{ FEEDBACK : rates
    EVENTS ||--o{ FEEDBACK : "rated in"

    USERS {
        bigint user_id PK
        citext email UK
        text full_name
        text city
        boolean is_active
    }
    ORGANIZATIONS {
        bigint org_id PK
        text name UK
        text slug UK
    }
    ORG_MEMBERS {
        bigint org_id PK, FK
        bigint user_id PK, FK
        member_role role "one owner per org"
    }
    VENUES {
        bigint venue_id PK
        text name
        text city
        text timezone "valid IANA zone"
        int capacity
    }
    ROOMS {
        bigint room_id PK
        bigint venue_id FK
        text name
        int capacity
    }
    EVENT_CATEGORIES {
        int category_id PK
        text name UK
        int parent_id FK
    }
    EVENTS {
        bigint event_id PK
        bigint org_id FK
        bigint venue_id FK
        int category_id FK
        text title
        event_status status "draft > published > completed"
        timestamptz starts_at
        timestamptz ends_at
        int capacity "<= venue capacity"
        tsvector search "generated"
    }
    SESSIONS {
        bigint session_id PK
        bigint event_id FK
        bigint room_id FK
        tstzrange during "no overlap per room"
    }
    SPEAKERS {
        bigint speaker_id PK
        text full_name
        citext email UK
    }
    SESSION_SPEAKERS {
        bigint session_id PK, FK
        bigint speaker_id PK, FK
        text role
    }
    TICKET_TYPES {
        bigint ticket_type_id PK
        bigint event_id FK
        text name
        numeric price
        int quantity_total
        int quantity_sold "0..quantity_total"
        timestamptz sales_start
        timestamptz sales_end
    }
    PROMO_CODES {
        bigint promo_id PK
        bigint event_id FK
        citext code
        text discount_type
        int max_uses
        int times_used
    }
    ORDERS {
        bigint order_id PK
        bigint user_id FK
        bigint event_id FK
        bigint promo_id FK
        order_status status
        numeric total "= subtotal - discount"
    }
    ORDER_ITEMS {
        bigint order_item_id PK
        bigint order_id FK
        bigint ticket_type_id FK
        int quantity
        numeric unit_price
    }
    PAYMENTS {
        bigint payment_id PK
        bigint order_id FK
        numeric amount
        payment_status status
        text provider_ref UK
    }
    REFUNDS {
        bigint refund_id PK
        bigint order_id FK
        bigint payment_id FK
        numeric amount "sum <= payment"
    }
    TICKETS {
        bigint ticket_id PK
        bigint order_item_id FK
        bigint event_id FK
        uuid code UK "QR code"
        ticket_status status
    }
    CHECK_INS {
        bigint check_in_id PK
        bigint ticket_id FK, UK "one entry per ticket"
        text gate
        timestamptz checked_in_at
    }
    WAITLIST {
        bigint waitlist_id PK
        bigint ticket_type_id FK
        bigint user_id FK
        waitlist_status status
        timestamptz offer_expires_at
    }
    FEEDBACK {
        bigint feedback_id PK
        bigint event_id FK
        bigint user_id FK
        smallint rating "1-5, attendees only"
    }
```

Not drawn: `app.scan_attempts` (log of every door scan, joined to tickets by `code`) and
`audit.change_log` (before/after values of changes to events, ticket types, orders, refunds and promo codes).

## Normalization

The schema is in third normal form, with two deliberate, constraint-protected exceptions:

| Denormalized column | Why | What keeps it correct |
|---|---|---|
| `tickets.event_id` (derivable through order_items → orders) | The door scanner checks "is this ticket for this event?" on every scan, and row-level security filters tickets by event | Trigger `tickets_event_check` rejects a value that differs from the order's event |
| `ticket_types.quantity_sold` (derivable by counting tickets) | Checking availability by counting tickets would scan thousands of rows inside the checkout's critical section | Changed only by `purchase_tickets` and `refund_order` under a row lock; `CHECK (quantity_sold BETWEEN 0 AND quantity_total)`; tests compare it with the real ticket count |
