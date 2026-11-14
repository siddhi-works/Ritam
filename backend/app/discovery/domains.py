"""Which websites are which: banks and card issuers, RBI and government, comparison sites, news
and forums. Shared by discovery and the India-only checks."""

import re
from urllib.parse import urlsplit

# Banks and card issuers. RBI reserves the .bank.in domain for regulated banks, so any *.bank.in
# host is treated as official as well.
ISSUER_DOMAINS = {
    "hdfcbank.com", "axisbank.com", "icicibank.com", "sbicard.com", "sbi.co.in", "kotak.com",
    "idfcfirstbank.com", "aubank.in", "indusind.com", "yesbank.in", "rblbank.com", "bankofbaroda.in",
    "pnbindia.in", "federalbank.co.in", "hsbc.co.in", "sc.com", "americanexpress.com", "onecard.app",
}  # fmt: skip
REGULATOR_DOMAINS = {"rbi.org.in", "cms.rbi.org.in", "sebi.gov.in", "npci.org.in"}
GOV_SUFFIXES = (".gov.in", ".nic.in", ".ac.in", ".edu.in")
AGGREGATOR_DOMAINS = {
    "paisabazaar.com", "bankbazaar.com", "cardinsider.com", "cardexpert.in", "groww.in", "finology.in",
    "cardadvisor.in", "wishfin.com", "bajajfinservmarkets.in", "creditkaro.com", "magicpin.in",
    }  # fmt: skip
FORUM_DOMAINS = {
    "technofino.in", "reddit.com", "quora.com", "facebook.com", "x.com", "twitter.com", "instagram.com",
    "youtube.com", "linkedin.com",
}  # fmt: skip
# Global banks whose India pages live under /in/; their other countries are not Indian terms.
GLOBAL_ISSUERS = {"americanexpress.com", "sc.com"}
# File hosts and marketplaces that re-upload random PDFs; never a source.
JUNK_DOMAINS = {"imimg.com", "scribd.com", "dokumen.pub", "pdfcoffee.com", "yumpu.com"}
NEWS_DOMAINS = {
    "economictimes.indiatimes.com", "livemint.com", "business-standard.com", "businesstoday.in",
    "moneycontrol.com", "financialexpress.com", "ndtvprofit.com", "thehindubusinessline.com",
    "timesofindia.indiatimes.com", "hindustantimes.com", "indianexpress.com", "news18.com",
}  # fmt: skip


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def matches(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify(url: str, title: str = "") -> tuple[str, bool]:
    """(kind, official) from the URL and title."""
    h = host(url)
    if h in GLOBAL_ISSUERS and "/in/" not in urlsplit(url).path.lower():
        return "aggregator", False  # the same bank's other countries are not Indian terms
    text = f"{url} {title}".lower()
    is_pdf = urlsplit(url).path.lower().endswith(".pdf")
    if matches(h, REGULATOR_DOMAINS):
        return "rbi_rule", True
    official = h.endswith(".bank.in") or matches(h, ISSUER_DOMAINS) or h.endswith(GOV_SUFFIXES)
    if official:
        if re.search(r"\bkfs\b|key[- ]fact", text):
            return "kfs_pdf", True
        if re.search(r"mitc|most[- ]important[- ]terms", text):
            return "mitc_pdf", True
        if re.search(r"notice|revision|revised|changes? in", text):
            return "bank_notice", True
        return (
            "mitc_pdf"
            if is_pdf and re.search(r"terms|t&c|tnc|conditions", text)
            else "official_page"
        ), True
    if matches(h, FORUM_DOMAINS):
        return "forum", False
    if matches(h, NEWS_DOMAINS):
        return "news", False
    return "aggregator", False  # comparison sites and other third-party pages
