# GGM Store - Exhaustive Application Architecture & Handoff Document

## 1. Project Overview
**GGM Store** is a hyper-local, micro-commerce platform built for a mini-supermarket to manage grocery deliveries to nearby apartments. It replaces an inefficient WhatsApp-based manual ordering process. 

The system serves three distinct user roles via a single Django application:
1. **Customers:** Browse a catalog, manage a session-based cart, checkout, and track live orders via a Progressive Web App (PWA).
2. **Staff (Shop Phone):** Manage orders, confirm payments, print driver manifests, update stock, modify orders (substitutions), and toggle store open/closed status.
3. **Owner/Admin:** View daily analytics, 7-day revenue trends, low-stock alerts, and manage configurations.

The platform prioritizes a low-friction, mobile-first workflow. It includes a manual/automated POS sync via Excel (`.xlsx`) uploads, native Web Push notifications (VAPID), and a custom variant grouping system to solve the limitations of the physical POS system.

---

## 2. Technology Stack
- **Backend Framework:** Django (Python)
- **Database:** PostgreSQL (Production on Render) / SQLite (Local development)
- **Package Manager:** `uv`
- **Frontend Interactivity:** HTMX (v1.9.12, loaded via CDN)
- **Styling:** Tailwind CSS (via CDN)
- **Icons:** Lucide Icons (via CDN, rendered via `<i data-lucide="...">`)
- **PWA:** Web App Manifest, Service Worker (`sw.js`), Web Push API (`pywebpush`, `py-vapid`)
- **Hosting:** Render

---

## 3. File Structure Tree

```text
ggm-store/
├── .env
├── .env.example
├── .env.prod
├── .gitignore
├── .python-version
├── README.md
├── Procfile
├── build.sh
├── manage.py
├── pyproject.toml
├── run.sh
├── runtime.txt
├── uv.lock
├── db.sqlite3
├── core/
│   ├── __init__.py
│   ├── asgi.py
│   ├── urls.py
│   ├── wsgi.py
│   └── settings/
│       ├── __init__.py
│       ├── base.py
│       ├── development.py
│       └── production.py
├── marketplace/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── context_processors.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── management/
│   │   └── commands/
│   └── migrations/
├── templates/
│   ├── base.html
│   ├── marketplace/
│   └── registration/
├── static/
│   └── (icons, css, sw.js, manifest.json)
├── staticfiles/
├── media/
├── data/
└── scripts/
```

---

## 4. Core Data Models (`marketplace/models.py`)
The application relies on the following core entities:

- **`StoreConfig`**: A singleton model (`pk=1`) storing global settings: `delivery_fee`, `free_delivery_threshold`, `minimum_order_value`, `is_open`, `closed_message`, and `whatsapp_number`.
- **`ProductGroup` & `Unit`**: Simple categorizations for products.
- **`Product`**: The core inventory item. Includes:
  - Standard POS fields: `code`, `name`, `cost_price`, `selling_price`, `stock_quantity`, `is_active`.
  - Variant fields: `parent_group` (groups items together, e.g., "Kakira Sugar") and `variant_label` (e.g., "1KG", "25KG").
  - Alert fields: `low_stock_threshold`, `manually_disabled`.
- **`Apartment`**: Represents a delivery location. Has a `delivery_fee_override` field (nullable) to bypass the global delivery fee for specific buildings.
- **`Customer`**: Identified by `phone_number`. Stores `name`, `apartment`, and `unit_number`. Session-based authentication is used via `request.session['customer_id']`.
- **`Order`**: Represents a placed order. Contains `status` (new, confirmed, packed, delivered, cancelled), `payment_method` (cash, momo), `total_amount`, `delivery_fee`, `note` (delivery instructions), `is_modified` (flag if staff changed items), and `rating`/`feedback`.
- **`OrderItem`**: Joins an `Order` to a `Product` with `quantity` and `price_at_time_of_order`.
- **`PushSubscription`**: Stores browser push endpoints (`endpoint`, `p256dh`, `auth`) linked to a `Customer`.
- **`FeaturedCampaign`**: Schedules featured products on the homepage (`starts_at`, `ends_at`, `products` M2M).

---

## 5. Global Template Context & Base Layout

### Context Processors (`marketplace/context_processors.py`)
Only one project-specific context processor is configured: `vapid_public_key`.
- `VAPID_PUBLIC_KEY` (str): Used in `base.html` meta tags and the push notification banner.

Django's standard processors provide `request`, `user`, `perms`, and `messages`. The `StoreConfig` object (`config`) is manually passed by most views.

### Base Template (`templates/base.html`)
- **Fonts & Styling:** Loads Inter via Google Fonts. Tailwind is configured via CDN with an extended theme setting `fontFamily.sans` to Inter.
- **Layout:** 
  - **Desktop:** Top header (hidden on mobile) with logo, "My Orders" link, and Cart link.
  - **Mobile:** Sticky bottom navigation (fixed) with Home, Orders, and Cart icons.
- **Shared JS:** Loads HTMX, Lucide Icons, and includes custom scripts for:
  - Injecting CSRF tokens (`X-CSRFToken`) into every HTMX request via the `<meta name="csrf-token">` tag.
  - Registering the Service Worker (`/sw.js`).
  - Handling the Web Push subscription flow.

---

## 6. Template Hierarchy & Partials
There are 27 HTML templates in total: `base.html`, `registration/login.html`, and 25 in `templates/marketplace/`.

### Full Page Templates (Extend `base.html`)
- `cart.html`, `checkout.html`, `customer_order_detail.html`, `customer_orders.html`, `home.html`, `order_success.html`, `owner_dashboard.html`, `product_detail.html`, `product_list.html`, `staff_order_detail.html`, `staff_orders.html`, `staff_settings.html`, `staff_stock.html`.

### Standalone Printable Pages (Do not extend `base.html`)
- `staff_manifest.html`: Printable driver checklist. Loads its own Tailwind and print-specific CSS.
- `staff_order_slip.html`: Printable receipt. Auto-triggers `window.print()`.

### HTMX Partials
- `_cart_body.html`: Swapped inside `#cart-body` on cart updates.
- `_checkout_summary.html`: Swapped inside `#checkout-summary` when apartment changes.
- `_order_status_partial.html`: Swapped inside `#order-status-container` for live tracking.
- `_product_variant_detail.html`: Swapped inside `#variant-detail-container` on the PDP.
- `_staff_order_items.html`: Swapped inside `#staff-order-items-container` when staff edits items.
- `_staff_order_list.html`: Swapped inside `#order-list-inner` on the staff dashboard.
- `_staff_product_row.html`: Swapped inside `#product-<id>` in stock management.
- `_staff_substitute_search.html`: Rendered inside `#substitute-results`.
- `_store_status_banner.html`: Swapped inside `#store-status-banner`.

---

## 7. HTMX Interaction Patterns & DOM Contracts
The UI heavily relies on HTMX. The following DOM targets, triggers, and endpoint behaviors are critical to the frontend architecture:

### Global / Cart
- **`#cart-count-desktop` & `#cart-count-mobile`**: Use `hx-get="{% url 'cart_count' %}"` with `hx-trigger="load, cartUpdated from:body"`.
- **Add to Cart (everywhere)**: Buttons use `hx-post="{% url 'add_to_cart' product.id %}"` and `hx-swap="none"`. The backend returns a new count and triggers `cartUpdated`.
- **Cart Updates**: `+`, `-`, and Remove buttons POST to `cart_update` with `hx-vals='{"action":"inc/dec/remove"}'` and target `#cart-body`.

### Product Detail Page (Variants)
- **Variant Buttons**: `hx-get="{% url 'product_variant_partial' v.id %}"` targeting `#variant-detail-container`.
- **Custom JS Requirement**: After the swap, vanilla JS updates the URL silently (`history.replaceState`) and swaps the active state classes on the `.variant-option` buttons.

### Customer Tracking
- **`#order-status-container`**: Uses `hx-get` with `hx-trigger="every 30s"` to poll the status. The polling is omitted entirely if the order status is `delivered` or `cancelled`.

### Staff Dashboard
- **`#order-list-container`**: Polls `staff_orders` every 20 seconds, targeting `#order-list-inner`.
- **Ringing Alert Contract**: The polling response includes an `HX-Trigger: staffOrdersUpdated` with `newCount` in the payload. Vanilla JS listens for this to play a generated Web Audio sound and flash the page title.
- **`#store-status-banner`**: Toggled via HTMX POST. 

### Staff Order Modifications
- **`#staff-order-items-container`**: Quantity adjustments and removals POST to `staff_modify_order_item`. Substitute searches use `keyup changed delay:300ms` to hit `staff_search_substitute`.

---

## 8. PWA & Web Push Configuration

- **Manifest**: `/static/manifest.json` (standalone mode, theme color `#ea580c`).
- **Service Worker (`/static/sw.js`)**:
  - Excludes `/staff`, `/cart`, `/admin`, `/checkout`, `/order`, `/login`, and `/logout` from cache fallbacks.
  - Listens for `push` events to display notifications using `requireInteraction` and a vibration pattern.
  - Listens for `notificationclick` to focus an existing window or open a new one.
- **Subscription Flow**:
  - `<meta name="vapid-public-key">` exposes the key.
  - The script in `base.html` requests `Notification.permission`.
  - If granted, it calls `pushManager.subscribe()` and POSTs the JSON to `/push/subscribe/`.
  - A prompt banner (`#push-prompt-banner`) is conditionally rendered on `home.html` if permissions are `default` and the user hasn't dismissed it recently. The prompt calls a global `requestNotificationPermission()` function.

---

## 9. Complex Frontend Logic (Vanilla JS)

There is no Alpine.js or React. All complex logic is handled by inline Vanilla JS.

1.  **CSRF Token Injection**: Global listener on `htmx:configRequest` reads `meta[name="csrf-token"]` and sets `evt.detail.headers['X-CSRFToken']`.
2.  **Staff Alert Sounds**: Located in `staff_orders.html`. Uses the Web Audio API to generate a two-tone "ding-dong" chime. Repeats every 3 seconds up to 60 seconds via `setInterval`. Stores the last seen order count in `localStorage` (`ggm_last_new_count`) to detect changes.
3.  **Variant URL History**: Located in `product_detail.html`. Uses `window.history.replaceState()` to change the URL to `/product/<id>/` when a variant is clicked, ensuring the back button works correctly.
4.  **Lucide Initialization**: Because HTMX swaps HTML dynamically, any HTMX target that receives new icons must run `lucide.createIcons()`. This is handled via `hx-on::after-swap="lucide.createIcons()"` on specific containers (e.g., `#cart-body`, `#order-list-inner`, `#staff-order-items-container`).
5.  **CSS Selection Styling**: The checkout payment method radio buttons rely on Tailwind arbitrary variants `:has(input:checked)` to apply the active styles when the radio input is selected.

