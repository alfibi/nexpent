from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, Optional


@dataclass(frozen=True)
class ProviderAccount:
    provider_account_id: str
    name: str
    mask: str
    institution_name: str
    account_type: str
    balance: Decimal
    available_balance: Decimal
    currency: str
    country: str


@dataclass(frozen=True)
class ProviderTransaction:
    provider_transaction_id: str
    provider_account_id: str
    amount: Decimal
    currency: str
    country: str
    merchant: str
    description: str
    category: str
    subcategory: Optional[str]
    payment_method: str
    date: date


class BankProvider(Protocol):
    provider_name: str

    def exchange_public_token(self, public_token: Optional[str], country: str) -> str:
        ...

    def list_accounts(self, access_token: str, country: str) -> list[ProviderAccount]:
        ...

    def list_transactions(self, access_token: str, account_ids: Optional[list[str]], country: str) -> list[ProviderTransaction]:
        ...

    def refresh_balances(self, access_token: str, country: str) -> list[ProviderAccount]:
        ...

