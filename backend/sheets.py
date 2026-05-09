import os

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials


def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not set")

    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key("1FLUFLCVKDOXI7rsJ4WOsus6G-VivXyGsZVLU5hWo-UE").sheet1


def get_clean_dataframe() -> pd.DataFrame:
    sheet = get_sheet()
    rows = sheet.get_all_records()

    normalized = [
        {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}
        for row in rows
    ]

    df = pd.DataFrame(normalized)

    required = ["amount", "category", "subcategory", "description", "payment_method", "date"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    df["amount"] = (
        pd.to_numeric(df["amount"], errors="coerce")
        .fillna(0)
        .astype("int64")
        .astype(int)
    )

    df["category"] = (
        df["category"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .str.title()
    )

    df["subcategory"] = (
        df["subcategory"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .str.title()
    )

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.assign(
        month=df["date"].dt.to_period("M").astype(str),
        day=df["date"].dt.day,
        year=df["date"].dt.year,
        weekday=df["date"].dt.day_name(),
        week=df["date"].dt.isocalendar().week,
        quarter=df["date"].dt.quarter,
    )

    return df
