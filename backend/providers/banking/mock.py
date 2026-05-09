from datetime import date, timedelta
from decimal import Decimal

from typing import Optional
from providers.banking.base import BankProvider, ProviderAccount, ProviderTransaction


class MockBankProvider(BankProvider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def exchange_public_token(self, public_token: Optional[str], country: str) -> str:
        return f"mock:{self.provider_name}:{country}:{public_token or 'sandbox'}"

    def _currency(self, country: str) -> str:
        return "INR" if country.upper() == "IN" else "GBP" if country.upper() == "GB" else "EUR" if country.upper() in {"DE", "FR", "NL", "ES"} else "USD"

    def list_accounts(self, access_token: str, country: str) -> list[ProviderAccount]:
        currency = self._currency(country)
        suffix = country.upper()
        return [
            ProviderAccount(
                provider_account_id=f"{self.provider_name}_{suffix}_checking",
                name="Everyday Checking",
                mask="1024",
                institution_name=f"{self.provider_name.title()} Sandbox Bank",
                account_type="checking",
                balance=Decimal("4820.75"),
                available_balance=Decimal("4610.25"),
                currency=currency,
                country=country.upper(),
            ),
            ProviderAccount(
                provider_account_id=f"{self.provider_name}_{suffix}_savings",
                name="High Yield Savings",
                mask="2048",
                institution_name=f"{self.provider_name.title()} Sandbox Bank",
                account_type="savings",
                balance=Decimal("12750.00"),
                available_balance=Decimal("12750.00"),
                currency=currency,
                country=country.upper(),
            ),
        ]

    def list_transactions(self, access_token: str, account_ids: Optional[list[str]], country: str) -> list[ProviderTransaction]:
        currency = self._currency(country)
        today = date.today()
        all_rows = [
            ProviderTransaction(
                provider_transaction_id=f"{self.provider_name}_{country}_salary_{today:%Y%m}",
                provider_account_id=f"{self.provider_name}_{country.upper()}_checking",
                amount=Decimal("5200.00"),
                currency=currency,
                country=country.upper(),
                merchant="Employer Payroll",
                description="Monthly payroll deposit",
                category="Income",
                subcategory="Salary",
                payment_method="bank_transfer",
                date=today.replace(day=1),
            ),
            ProviderTransaction(
                provider_transaction_id=f"{self.provider_name}_{country}_coffee_{today:%Y%m%d}",
                provider_account_id=f"{self.provider_name}_{country.upper()}_checking",
                amount=Decimal("-6.75"),
                currency=currency,
                country=country.upper(),
                merchant="Neighborhood Coffee",
                description="Card payment at Neighborhood Coffee",
                category="Food & Drinks",
                subcategory="Coffee",
                payment_method="card",
                date=today - timedelta(days=1),
            ),
            ProviderTransaction(
                provider_transaction_id=f"{self.provider_name}_{country}_grocery_{today:%Y%m%d}",
                provider_account_id=f"{self.provider_name}_{country.upper()}_checking",
                amount=Decimal("-86.42"),
                currency=currency,
                country=country.upper(),
                merchant="City Grocers",
                description="Debit card purchase at City Grocers",
                category="Groceries",
                subcategory="Household",
                payment_method="card",
                date=today - timedelta(days=3),
            ),
            ProviderTransaction(
                provider_transaction_id=f"{self.provider_name}_{country}_savings_{today:%Y%m}",
                provider_account_id=f"{self.provider_name}_{country.upper()}_savings",
                amount=Decimal("650.00"),
                currency=currency,
                country=country.upper(),
                merchant="Internal Transfer",
                description="Transfer to savings",
                category="Savings",
                subcategory="Automatic transfer",
                payment_method="bank_transfer",
                date=today - timedelta(days=5),
            ),
        ]
        if not account_ids:
            return all_rows
        return [row for row in all_rows if row.provider_account_id in set(account_ids)]

    def refresh_balances(self, access_token: str, country: str) -> list[ProviderAccount]:
        return self.list_accounts(access_token, country)

