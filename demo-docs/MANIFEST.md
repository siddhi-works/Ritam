# Demo documents

Real, public documents used for Ritam's preloaded demo audits, downloaded on 31 Oct 2026 by Ritam's own
fetcher (SSRF-guarded, size-capped). The files stay out of git (size, copyright); this manifest is committed
so anyone can re-download each file from its source and check the SHA-256. Machine-readable copy: `manifest.json`.

| File | What it is | Source | Pages | Dates Ritam found | SHA-256 (first 16) |
|---|---|---|---|---|---|
| `axis_mitc_new.pdf` | Axis Bank MITC for credit cards (current) | [link](https://www.axis.bank.in/docs/default-source/default-document-library/mitc-credit-cards.pdf) | 62 | effective 2026-08-28, published 2021-01-04, via text:effective (0.9) | `a04b3b38a49cbeed` |
| `axis_magnus_revision_notice.pdf` | Axis Bank: revision of MAGNUS credit card T&C (effective 28 Aug 2026) | [link](https://campaign.axis.bank.in/generic/terms-and-conditions-magnus.pdf) | 2 | effective 2026-11-15, published 2026-07-27, via text:effective (0.9) | `245d7a09d5a0322b` |
| `axis_select_revision_notice.pdf` | Axis Bank: revision of SELECT credit card T&C (effective 28 Aug 2026) | [link](https://campaign.axis.bank.in/generic/terms-and-conditions-select.pdf) | 3 | effective 2026-11-15, published 2026-07-27, via text:effective (0.9) | `296d8cdcfc8e56e1` |
| `hdfc_millennia_terms.pdf` | HDFC Bank Millennia credit card document | [link](https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/personal-banking/discover-products/cards/credit-cards/millennia-credit-card/hdfc-bank-millennia-credit-card.pdf) | 6 | effective 2023-02-01, published 2024-11-26, via text:effective (0.9) | `b37a309bc5614f50` |
| `hdfc_millennia_fees_2022.pdf` | HDFC Millennia microsite fees & features PDF (2022) | [link](https://v.hdfc.bank.in/content/dam/hdfc-aem-microsites/millennia-cards/pdfs/CreditCard.pdf) | 2 | published 2019-12-10, via pdf_meta:modified (0.45) | `26c04643e1a7eae5` |
| `icici_mitc.pdf` | ICICI Bank credit card MITC | [link](https://www.icici.bank.in/content/dam/icicibank/india/managed-assets/revamp-page-images/docs/pdf/mitc_cc.pdf) | 48 | effective 2026-11-10, published 2026-10-16, via text:effective (0.9) | `64d0649be493d51a` |
| `icici_amazon_pay_mitc.pdf` | ICICI Amazon Pay credit card MITC | [link](https://www.icici.bank.in/content/dam/icicibank/india/managed-assets/revamp-page-images/docs/pdf/mitc-cc-gk-t.pdf) | 13 | effective 2026-03-01, published 2019-04-15, via text:effective (0.9) | `4207fc25a47e9e5b` |
| `aggregator_paisabazaar_magnus.html` | Paisabazaar: Axis Magnus page | [link](https://www.paisabazaar.com/axis-bank/magnus-credit-card/) | 1 | effective 2024-04-20, published 2026-10-12, via text:effective (0.9) | `0c95ab0ebcb83e5f` |
| `aggregator_paisabazaar_millennia.html` | Paisabazaar: HDFC Millennia page | [link](https://www.paisabazaar.com/hdfc-bank/millennia-credit-card/) | 1 | effective 2023-02-01, published 2026-06-05, via text:effective (0.9) | `5e139e43e3504d00` |
| `aggregator_bankbazaar_millennia.html` | BankBazaar: HDFC Millennia page | [link](https://www.bankbazaar.com/credit-card/hdfc-bank-millenia-credit-card.html) | 1 | published 2026-10-31, via text:updated (0.8) | `60d82a244a546b4e` |

**Pending:** `axis_mitc_old_wayback_2025-08-09.pdf`, the Axis MITC as archived on 9 Aug 2025 (the Wayback Machine
was rate-limiting us). Source: https://web.archive.org/web/20250809103732id_/https://www.axisbank.com/docs/default-source/default-document-library/mitc-credit-cards.pdf

**Notes from parsing:**
- Axis's Magnus and Select revision notices state effective dates (28-08-2026, 15-11-2026) but no notice date; the PDFs were created on 27 Jul 2026. Ritam uses that timestamp only as an *inferred* announcement date (UNCERTAIN).
- BankBazaar's page shows a 'last updated' date equal to the day it was fetched (dynamic), so page dates on comparison sites are not evidence of freshness.
- The 2022 HDFC Millennia fees PDF has no date in its text (only a 2019 file timestamp), so Ritam marks it undated.
