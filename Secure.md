# Secure.md (The Shield)

## User Auth (OAuth2 for Pinterest + JWT)

Auth ko strong banao taaki data safe rahe.

- **OAuth2**: Pinterest se login, access tokens get karo.
- **JWT**: Session management, tokens expire in 1 hour.
- **Mobile-friendly**: OAuth flows mobile browsers mein work karte hain.

Steps:
1. Pinterest app register karo.
2. JWT library (PyJWT) use karo.
3. Refresh tokens implement karo.

Checklist:
- [ ] OAuth2 flow test karo.
- [ ] Tokens encrypt karo.

## Proxy Management: Preventing Pinterest Shadowbans/Blocks

Pinterest blocks aggressive posting.

- **Proxies**: Rotating proxies use karo (Bright Data, Oxylabs).
- **Management**: Proxy pool maintain karo, failed ones rotate.
- **Detection**: IP bans detect karo, switch proxies.

Edge case: If all proxies blocked, user notify karo.

## Rate Limiting (User-level and API-level)

Limits set karo taaki abuse na ho.

- **User-level**: 50 posts/hour per user.
- **API-level**: Pinterest 1000/hr, Flux 100/day.
- **Implementation**: Redis for counters, middleware in FastAPI.

Rate limiting table:

| Level | Limit | Action |
|-------|-------|--------|
| User | 50/hr | Throttle |
| Pinterest | 1000/hr | Backoff |
| Flux | 100/day | Queue |

## Data Encryption: Protecting Affiliate IDs and API Keys

Sensitive data encrypt karo.

- **Encryption**: AES-256 for data at rest, TLS for transit.
- **Storage**: Keys in env vars, data in encrypted DB.
- **Mobile**: End-to-end encryption for user data.

Checklist:
- [ ] Cryptography library use karo.
- [ ] Keys rotate regularly.

## Secure Payment Gateway Integration (Stripe/LemonSqueezy)

Payments handle karo safely.

- **Gateways**: Stripe for global, LemonSqueezy for indie devs.
- **Integration**: Webhooks for confirmations, PCI compliant.
- **Mobile**: Payment links generate karo.

Steps:
1. Gateway account banao.
2. Webhooks handle karo for success/fail.
3. Refunds logic add karo.

Edge cases: Failed payments, chargebacks.