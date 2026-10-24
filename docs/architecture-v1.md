# GGM Store Frontend Architecture Handoff

This document describes the current Django-rendered frontend, its template and view data flow, HTMX interactions, and PWA behavior. It is intended to help a UI agent replace the presentation layer without losing the existing workflows or integration contracts.

## 1. Global Template Context

### Custom context processor

The only project-specific context processor configured in `core/settings/base.py` is `marketplace.context_processors.vapid_public_key`.

| Variable | Type | Meaning / use |
|---|---|---|
| `VAPID_PUBLIC_KEY` | `str` (possibly empty) | Public VAPID key read from Django settings. The base template publishes it in a meta tag, and the home page checks it before rendering the push-permission prompt. |

The private VAPID key and VAPID admin email are settings used by backend push delivery; they are not exposed by the template context processor.

### Django-provided context

The configured built-in processors also provide:

| Variable | Type | Meaning |
|---|---|---|
| `request` | `HttpRequest` | Current request object. |
| `user` | Auth user or `AnonymousUser` | Current authenticated user; staff pages use `user.is_superuser` for the owner-dashboard link. |
| `perms` | Django `PermWrapper` | Permission checks for the current user. |
| `messages` | Message storage / iterable | Flash messages rendered on pages such as home, checkout, login, and staff settings. |

`CSRF_TRUSTED_ORIGINS` is a Django security setting configured from the environment in `core/settings/base.py` (and overridden in `dev.py`). It is not passed to templates and should not be treated as frontend data.

`VAPID_PUBLIC_KEY` is the only project setting explicitly exposed to templates. The templates do not directly read other uppercase settings. The base template creates a `csrf-token` meta tag using `{{ csrf_token }}`, and its JavaScript reads that tag for HTMX and push-subscription requests. However, the configured context processors do **not** include `django.template.context_processors.csrf`. Individual POST forms use `{% csrf_token %}`, but the meta tag's token should be verified in rendered pages before relying on it in JavaScript.

### View-specific context

Most business data is supplied by individual views, not globally. Frequently used view context includes:

- `config`: the `StoreConfig` instance, used for open/closed state, delivery settings, WhatsApp contact, and customer-facing availability.
- `product`, `variants`, `group`, `products`, `search_results`, `featured_products`, `frequent_products`: catalog and variant data.
- `items`, `subtotal`, `delivery_fee`, `grand_total`, `amount_for_free_delivery`: cart/checkout totals.
- `order`, `orders`, `customer`, `status`, `new_count`, `confirmed_count`, `packed_count`, `delivered_count`: customer and staff order workflows.
- `form_data`, `apartments`, `item_count`: checkout form state.
- Other page-specific values include `status_to_notify`, `whatsapp_message`, `customer_whatsapp_number`, `q`, `filter_type`, and owner-dashboard metrics.

## 2. Current UI Framework and Dependencies

### CSS and design system

- The main application uses **Tailwind CSS from its CDN** (`https://cdn.tailwindcss.com`) with the default utility palette. It is not Bootstrap, DaisyUI, or Flowbite.
- `base.html` customizes Tailwind only to set the sans font stack to **Inter**, loaded from Google Fonts. No additional Tailwind plugins are configured.
- The dominant brand color is Tailwind orange (`orange-600`, corresponding to `#ea580c`); most page surfaces and text use `slate-*`, with green, red, blue, indigo, and yellow for status and feedback.
- No project CSS variables or bespoke design-token system were found in Django settings or the base template.
- The base template links `/static/css/style.css`, but the repository contains `static/css/styles.css` (plural), and that file is currently empty. The custom stylesheet therefore does not currently contribute styles through that link.
- `staff_manifest.html` is a standalone printable page: it loads Tailwind separately and defines print-specific rules in an inline `<style>`. `staff_order_slip.html` is also standalone and contains its own print-oriented styling.

### JavaScript

`base.html` loads these shared browser libraries:

1. **HTMX 1.9.12** from `unpkg.com`, used for partial requests and live updates.
2. **Lucide Icons** from `unpkg.com/lucide@latest`, rendered from `data-lucide` attributes. The base template initializes icons on initial page load; some HTMX targets reinitialize them after swaps.
3. **Custom vanilla JavaScript** for HTMX CSRF headers, service-worker registration, push subscriptions, and icon initialization.

There is no Alpine.js usage or other shared JavaScript framework evident in the templates.

## 3. Template Structure and Inheritance

There are 27 HTML templates: `templates/base.html`, `templates/registration/login.html`, and 25 templates in `templates/marketplace/`.

### Templates that extend `base.html`

- `templates/registration/login.html`
- `templates/marketplace/cart.html`
- `templates/marketplace/checkout.html`
- `templates/marketplace/customer_order_detail.html`
- `templates/marketplace/customer_orders.html`
- `templates/marketplace/home.html`
- `templates/marketplace/order_success.html`
- `templates/marketplace/owner_dashboard.html`
- `templates/marketplace/product_detail.html`
- `templates/marketplace/product_list.html`
- `templates/marketplace/staff_order_detail.html`
- `templates/marketplace/staff_orders.html`
- `templates/marketplace/staff_settings.html`
- `templates/marketplace/staff_stock.html`

These templates override the base `title` and/or `content` blocks. The base supplies the shared header, mobile bottom navigation, cart count indicators, footer, meta tags, shared CDN scripts, and service-worker/push JavaScript.

### Standalone pages

- `templates/marketplace/staff_manifest.html` — printable driver manifest; does not extend the base.
- `templates/marketplace/staff_order_slip.html` — printable order slip; does not extend the base.

### Partial templates and injection points

Partials are returned directly by HTMX views or included into full pages:

| Partial | Included/rendered by |
|---|---|
| `_cart_body.html` | Included in `cart.html`; returned by the cart-update endpoint and swapped into `#cart-body`. |
| `_checkout_summary.html` | Included in `checkout.html`; returned when the checkout apartment selection changes and swapped into `#checkout-summary`. |
| `_order_status_partial.html` | Included in `customer_order_detail.html`; returned for HTMX requests to the customer order-detail route and swapped into `#order-status-container`. |
| `_product_image_placeholder.html` | Reused where product images may be absent, including staff order-item rendering. |
| `_product_variant_detail.html` | Included initially in `product_detail.html`; returned for a selected variant and swapped into `#variant-detail-container`. |
| `_staff_order_items.html` | Included in `staff_order_detail.html`; returned after staff edits and replaces `#staff-order-items-container`. It also includes the product-image placeholder. |
| `_staff_order_list.html` | Included initially in `staff_orders.html`; returned by HTMX polling and swapped into `#order-list-inner`. |
| `_staff_product_row.html` | Included in `staff_stock.html`; returned after stock visibility is toggled and replaces the matching product row. |
| `_staff_substitute_search.html` | Returned for substitute searches and rendered into `#substitute-results`. |
| `_store_status_banner.html` | Included in `staff_orders.html`; returned after the store open/closed toggle and replaces `#store-status-banner`. |

### Complete `templates/` inventory

```text
templates/
├── base.html
├── registration/
│   └── login.html
└── marketplace/
    ├── _cart_body.html
    ├── _checkout_summary.html
    ├── _order_status_partial.html
    ├── _product_image_placeholder.html
    ├── _product_variant_detail.html
    ├── _staff_order_items.html
    ├── _staff_order_list.html
    ├── _staff_product_row.html
    ├── _staff_substitute_search.html
    ├── _store_status_banner.html
    ├── cart.html
    ├── checkout.html
    ├── customer_order_detail.html
    ├── customer_orders.html
    ├── home.html
    ├── order_success.html
    ├── owner_dashboard.html
    ├── product_detail.html
    ├── product_list.html
    ├── staff_manifest.html
    ├── staff_order_detail.html
    ├── staff_order_slip.html
    ├── staff_orders.html
    ├── staff_settings.html
    └── staff_stock.html
```

## 4. HTMX Interaction Patterns

### Important HTMX endpoints

| Route / view | Response | Interaction |
|---|---|---|
| `cart_count` — `/cart/count/` | Plain-text item count | Requested on load and after the `cartUpdated` event for desktop and mobile cart badges. |
| `add_to_cart` — `/cart/add/<product_id>/` | Plain-text count; emits `HX-Trigger: cartUpdated` | Adds one unit from home, category listings, or the product detail partial. The button uses `hx-swap="none"`; the global count badges update from the event. |
| `cart_update` — `/cart/update/<product_id>/` | `_cart_body.html` | Increments, decrements, or removes a cart item; replaces cart content and emits `cartUpdated`. |
| `checkout_summary_partial` — `/checkout/summary/` | `_checkout_summary.html` | Refreshes totals when the apartment selector changes. |
| `customer_order_detail` — `/my-orders/<order_id>/` | Full page for normal request; `_order_status_partial.html` for `HX-Request: true` | Periodically refreshes the customer order-status stepper. |
| `staff_orders` — `/staff/` | Full page for normal request; `_staff_order_list.html` for HTMX request | Polls the current status-filtered list; emits `staffOrdersUpdated` after swap with the current new-order count. |
| `staff_toggle_store_status` — `/staff/toggle-store/` | `_store_status_banner.html` | Replaces the store status banner. |
| `staff_modify_order_item` — `/staff/order/<order_id>/item/<item_id>/<action>/` | `_staff_order_items.html` | Changes quantity or removes an item, recalculates order totals, and refreshes the editable item section. |
| `staff_search_substitute` — `/staff/order/<order_id>/search-substitute/` | `_staff_substitute_search.html` | Returns matching active, priced products for the substitute search field. |
| `staff_add_substitute` — `/staff/order/<order_id>/add-substitute/<product_id>/` | `_staff_order_items.html` | Adds a product to the order and refreshes items and totals. |
| `staff_toggle_stock` — `/staff/stock/<product_id>/toggle/` | `_staff_product_row.html` | Replaces the corresponding stock row after toggling visibility/availability. |
| `product_variant_partial` — `/product/<product_id>/variant/` | `_product_variant_detail.html` | Refreshes price, stock state, description, and add-to-cart control for the selected product variant. |
| `log_whatsapp_notification` — `/staff/order/<order_id>/log-wa/<status_sent>/` | Empty `204` response on success | Hidden HTMX element logs a staff click on the WhatsApp notification link; it does not render UI. |

### Triggers and DOM contracts to preserve

- **Shared cart badges:** `hx-trigger="load, cartUpdated from:body"` on `#cart-count-desktop` and `#cart-count-mobile`.
- **Cart updates:** increment/decrement/remove buttons POST to `cart_update`; `hx-vals` sends `{"action":"inc"}`, `{"action":"dec"}`, or `{"action":"remove"}` and swaps the returned partial into `#cart-body`. Keep the enclosing target ID and action values.
- **Checkout:** `#checkout-apartment` uses `hx-trigger="change"`, includes the apartment field, and targets `#checkout-summary`.
- **Customer order tracking:** `#order-status-container` polls with `every 30s` while the order is not delivered or cancelled. The terminal states intentionally omit the polling attributes.
- **Staff order dashboard:** `#order-list-container` polls with `every 20s` and sends the selected status query. Its inner target is `#order-list-inner`. The `staffOrdersUpdated` event is used by the notification script.
- **Substitute search:** input uses `hx-trigger="keyup changed delay:300ms"` and targets `#substitute-results`.
- **Product variants:** variant buttons GET the variant partial into `#variant-detail-container`; after the request, vanilla JavaScript updates selected-button state and the browser URL.
- **Staff item controls:** quantity and remove buttons POST and replace the outer `#staff-order-items-container`. Search-result buttons use the same target to refresh the item section after adding a substitute.
- **Stock rows/store banner:** row and banner IDs are replacement targets (`#product-<id>` and `#store-status-banner`).
- Several swapped regions call `lucide.createIcons()` in `hx-on::after-swap` so icons in new markup render. Preserve equivalent icon initialization if changing those swap boundaries.

The shared HTMX configuration adds an `X-CSRFToken` header using the base `csrf-token` meta tag. POST forms also use Django `{% csrf_token %}` inputs.

## 5. PWA and Service Worker

### Base template setup

`base.html` includes:

- `/static/manifest.json`
- `theme-color` `#ea580c`
- Apple web-app capability/status/title metadata
- Apple touch icon and favicon
- `vapid-public-key`, `push-subscription-url`, and `csrf-token` meta elements
- Service-worker registration at `/sw.js` with root scope `/`

The `service_worker` view serves `static/sw.js` as JavaScript, sets `Service-Worker-Allowed: /`, and disables caching of the worker script.

### Push subscription flow

1. On window load, the base script registers `/sw.js`. If notification permission is already granted, it attempts to subscribe/register the current browser subscription with the backend.
2. On the home page, when `VAPID_PUBLIC_KEY` exists, `#push-prompt-banner` is rendered hidden. A page script shows it only if service workers, push, and notifications are supported, permission is still `default`, and the user has not dismissed it for the current seven-day period.
3. The Enable button calls the global `requestNotificationPermission()` function. It requests permission, waits for `navigator.serviceWorker.ready`, then calls `subscribeUserToPush`.
4. `subscribeUserToPush` reuses an existing subscription or creates one using the VAPID public key, then POSTs the subscription JSON to the URL in `meta[name="push-subscription-url"]` with JSON and CSRF headers. A non-OK response is treated as a failure.
5. On success, the prompt is hidden. Denied permission hides the prompt; dismissing it records `push_dismissed_until` in `localStorage`.

DOM/API contracts that the replacement UI should retain unless the JavaScript is updated in tandem:

- Meta elements: `meta[name="vapid-public-key"]`, `meta[name="push-subscription-url"]`, and `meta[name="csrf-token"]`.
- `#push-prompt-banner` and its Enable/dismiss actions.
- Global `requestNotificationPermission()` function.
- `save_push_subscription` endpoint, which accepts an `application/json` subscription payload.

### Service-worker behavior

- Pre-caches the home page, manifest, and primary icons during installation, then claims clients and removes older named caches during activation.
- For same-origin GET requests, static assets use cache-first behavior. Other eligible pages use network-first behavior with cached fallback.
- Requests under `/staff`, `/cart`, `/admin`, `/checkout`, `/order`, `/login`, and `/logout` are excluded from its fetch caching logic.
- Push events display notifications using the app icon, vibration, and `requireInteraction`; notification clicks focus an existing matching window or open the target URL. Non-same-origin notification destinations are redirected to `/`.
- The exclusion list does not include `/my-orders/`; the generic same-origin GET caching path can therefore cache successful customer order pages. The UI handoff should not assume those pages are excluded from service-worker caching.

## 6. Complex Frontend Logic

There is no Alpine.js dependency, and no substantial client-side application framework. The nontrivial behavior is implemented in inline vanilla JavaScript, HTMX attributes, and CSS.

### Home page: push prompt

`home.html` controls when the push banner appears and persists dismissal in `localStorage` for seven days. The permission/subscription implementation itself is in `base.html`.

### Product detail: variant selection

`product_detail.html` implements:

- HTMX request of a selected variant's detail partial.
- `updateVariantSelection()` to update `aria-pressed` and selected/unselected utility classes.
- `updateUrl()` using `history.replaceState()` to make the address correspond to the selected product without a full navigation.
- Lucide icon reinitialization after changing the selected variant.

Preserve the `.variant-option` class, `data-product-id`, selected-state accessibility attributes, and the `#variant-detail-container` target or update the associated JavaScript.

### Staff dashboard: new-order sound and alerts

`staff_orders.html` contains the most involved page-specific script. It listens for changes in the new-order count returned through `staffOrdersUpdated`, and:

- Plays a two-tone sound using Web Audio after a user interaction has enabled audio.
- Repeats the sound every three seconds for at most 60 seconds.
- Shows `#ring-banner`, flashes the document title, and stops when the STOP button (`#ring-stop-btn`) is clicked.
- Stores the last observed order count in `localStorage` under `ggm_last_new_count`.
- Checks counts periodically in addition to handling the HTMX event.

Preserve the `data-new-count` value on `#order-list-container`, event name and `event.detail.newCount` payload, banner/stop element IDs, and polling behavior if replacing this dashboard.

### Print pages

- `staff_order_slip.html` automatically opens the print dialog shortly after page load and also has a manual print button.
- `staff_manifest.html` has manual Print and Close controls and print-specific CSS.

### CSS-driven and inline behaviors

- Checkout payment options use CSS `:has(input:checked)` selectors for selected styling.
- The staff notification link has an HTMX click listener on a hidden element to log the WhatsApp notification without interrupting navigation.
- Product cards, cart controls, status filters, and staff forms otherwise rely on normal links/forms and HTMX rather than custom modals or Alpine components. No modal/dropdown framework was found.

## 7. Page and Data-Flow Map

### Customer storefront

- **Home/search:** `home` supplies product groups, search results, featured products, recently ordered products for the session's customer, and store configuration. Search results are grouped with `_group_products`; grouped cards link to the product detail page, while standalone products can be added directly.
- **Category listing:** `product_list` filters active, priced products for the selected group and groups variants for display.
- **Product detail:** `product_detail` provides a selected product and its active sibling variants. Variant selection only replaces the detail partial; add-to-cart still targets the selected product ID.
- **Cart:** quantities are stored in the session under product-ID keys. HTMX add/update operations refresh the shared cart badge and cart-body totals.
- **Checkout:** cart values and selected apartment determine subtotal, delivery fee, total, and free-delivery progress. Successful POST updates/creates a customer, creates the order and order items, and clears the session cart.
- **Order tracking:** customer ownership is based on `customer_id` in the session. The status partial polls until a terminal status; order items, payment, delivery fee, total, contact links, and any modification banner are rendered on the full detail page.

### Staff operations

- **Orders dashboard:** staff can filter order statuses, see periodic list refreshes, toggle store open/closed state, and use the order-count alert.
- **Order detail:** staff can change the order status/payment method, log WhatsApp notification clicks, change or remove items, and add substitute products. Item changes recalculate subtotal/delivery fee/total, set `is_modified`, and attempt a customer push notification.
- **Stock:** staff search/filter products and toggle availability; a single product row is HTMX-replaced.
- **Settings:** staff edit delivery thresholds, closed-store message, and WhatsApp number, and upload a stock workbook.
- **Manifest and order slip:** separate printable outputs for driver/staff workflows.
- **Owner dashboard:** superusers can access order/revenue/product summary data.

## 8. Useful Backend and Static Entry Points

- `core/urls.py` mounts Django admin, Django authentication URLs, and `marketplace.urls`.
- `marketplace/urls.py` contains the named routes used throughout templates. Use Django `{% url %}` names rather than hard-coded paths when introducing or moving links.
- `marketplace/views.py` owns page contexts and HTMX response selection. Some endpoints share a URL between full-page and partial responses based on the `HX-Request` header.
- `core/settings/base.py` defines the Django template directory, configured context processors, static/media paths, and common settings. `core/settings/dev.py` and `core/settings/prod.py` inherit from it and provide environment-specific overrides.
- `static/manifest.json` defines the PWA name, start URL, scope, standalone display mode, theme/background colors, and icon assets.
- `static/sw.js` implements caching and push/notification-click behavior.
- Static app-owned assets are under `static/`; collected deployment assets are under `staticfiles/`. The latter is generated output and should not be treated as the source of truth.
