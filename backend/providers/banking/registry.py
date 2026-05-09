from fastapi import HTTPException

from providers.banking.base import BankProvider
from providers.banking.mock import MockBankProvider


SUPPORTED_PROVIDERS = {
    "plaid": {"countries": {"US"}, "label": "Plaid"},
    "mx": {"countries": {"US"}, "label": "MX"},
    "finicity": {"countries": {"US"}, "label": "Finicity"},
    "account_aggregator": {"countries": {"IN"}, "label": "Account Aggregator"},
    "open_banking": {"countries": {"GB", "EU", "DE", "FR", "NL", "ES"}, "label": "Open Banking"},
}


def get_bank_provider(provider_name: str, country: str) -> BankProvider:
    normalized = provider_name.strip().lower()
    country_code = country.strip().upper()
    if normalized not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported bank provider")
    supported_countries = SUPPORTED_PROVIDERS[normalized]["countries"]
    if country_code not in supported_countries and "EU" not in supported_countries:
        raise HTTPException(status_code=400, detail="Provider is not configured for this country")
    return MockBankProvider(normalized)

