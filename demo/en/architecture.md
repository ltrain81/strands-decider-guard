# Order service
The order service reads from the `orders` table and publishes `OrderPlaced` events to EventBridge.
Customer contact fields (name, phone, email) are stored encrypted in the `customers` table and are never logged.
Retries use exponential backoff with jitter; the DLQ is drained by an hourly Lambda.
