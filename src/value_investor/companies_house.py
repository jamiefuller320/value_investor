"""Companies House filing helpers (re-exported for ingest tooling).

Implementation lives in ``value_investor.research.companies_house``; this module
exposes the public surface referenced by engineering task allowlists.
"""

from value_investor.research.companies_house import (  # noqa: F401
    CH_API_BASE,
    CH_DOCUMENT_API_BASE,
    DEEPEN_MAX_ACCOUNTS,
    DEFAULT_COMPANY_MAP_PATH,
    DEFAULT_MAX_ACCOUNTS,
    DOCUMENT_MIME_PRIORITY,
    MIME_PDF,
    MIME_XHTML,
    MIME_XML,
    companies_house_api_key,
    fetch_accounts_filing_rows,
    fetch_document_bytes,
    fetch_document_metadata,
    fetch_filings_companies_house,
    iter_ch_document_downloads,
    load_company_number_map,
    resolve_company_number,
    save_company_number_map,
    search_company_number,
)

__all__ = [
    "CH_API_BASE",
    "CH_DOCUMENT_API_BASE",
    "DEEPEN_MAX_ACCOUNTS",
    "DEFAULT_COMPANY_MAP_PATH",
    "DEFAULT_MAX_ACCOUNTS",
    "DOCUMENT_MIME_PRIORITY",
    "MIME_PDF",
    "MIME_XHTML",
    "MIME_XML",
    "companies_house_api_key",
    "fetch_accounts_filing_rows",
    "fetch_document_bytes",
    "fetch_document_metadata",
    "fetch_filings_companies_house",
    "iter_ch_document_downloads",
    "load_company_number_map",
    "resolve_company_number",
    "save_company_number_map",
    "search_company_number",
]
