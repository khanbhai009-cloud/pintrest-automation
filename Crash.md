# Crash.md (Emergency Protocol)

## Error Handling: What Happens When Flux API is Down?

Failures ko gracefully handle karo.

- **Flux Down**: Fallback to static images, user notify.
- **Pinterest Down**: Queue posts, retry later.
- **General**: Try-catch blocks, custom exceptions.

Error types:
- Network: Retry with backoff.
- Auth: Re-auth user.
- Rate: Wait and retry.

## Retry Logic: Exponential Backoff for Failed Posts

Failed tasks ko retry karo intelligently.

- **Backoff**: 1s, 2s, 4s... up to 5 min.
- **Max Retries**: 5 attempts.
- **Implementation**: Tenacity library use karo.

Checklist:
- [ ] Backoff algo implement karo.
- [ ] Max retries set karo.

## Wallet/Balance Management: Stopping Bot if Credits Over

Credits track karo, over pe stop.

- **Management**: DB mein balance store, deduct per task.
- **Stopping**: If balance < 0, halt all operations.
- **Notifications**: Low balance alerts.

Edge case: Concurrent deductions, race conditions handle karo.

## Logging & Monitoring: Sentry/LogRocket

Issues track karo.

- **Logging**: Structured logs with levels (info, error).
- **Monitoring**: Sentry for errors, LogRocket for user sessions.
- **Alerts**: Slack/email for critical issues.

Tools setup:
- Sentry: Error tracking.
- LogRocket: Session replays.

## User Notification System for Downtime or Failed Tasks

Users ko inform karo.

- **Channels**: Email, in-app notifications.
- **Events**: API down, task fail, balance low.
- **Templates**: Friendly messages in Hinglish.

Notification checklist:
- [ ] Email service integrate (SendGrid).
- [ ] Templates banao.
- [ ] Retry notifications if fail.