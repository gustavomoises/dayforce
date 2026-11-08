"""Catalog defaults and limits (architecture.md, Database setup flow, step 2)."""

PROMPT_NAME = "incident-catalog"

DEFAULT_SERVICES: tuple[str, ...] = (
    "api-gateway",
    "auth-service",
    "user-service",
    "payroll-service",
    "timesheet-service",
    "benefits-service",
    "payments-api",
    "billing-service",
    "checkout-service",
    "order-service",
    "inventory-service",
    "shipping-service",
    "notification-service",
    "email-service",
    "search-service",
    "reporting-service",
    "data-pipeline",
    "message-queue",
    "file-storage",
    "web-frontend",
)
DEFAULT_EVENTS_PER_SERVICE = 25

MAX_SERVICES = 50
MAX_EVENTS_PER_SERVICE = 50
