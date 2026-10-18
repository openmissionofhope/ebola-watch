# Contributing

Thank you for helping. The most valuable contributions are:

1. **Native-speaker review of language lexicons** (`data/lexicons/`). Sango,
   Kikongo/Kituba, Tshiluba, Kinyarwanda, Kirundi, Luganda, Acholi, Amharic,
   Tigrinya, Juba Arabic, Lingala, Swahili and Arabic all need review. Set
   `review_status: reviewed` only after native-speaker review, and include
   regional variants.
2. **Verification of transport corridors** (`data/transport/corridors.yaml`):
   operating status of passenger services, with a public source and date.
3. **Official data sources** for additional countries, with their access terms.
4. **Evaluation**: labelled historical signals and outcomes to measure detection
   lead time and false-alert rates.

Ground rules:

* Never add real patient, contact or personal data — tests use synthetic data.
* Never present synthetic data as real.
* Keep categories (confirmed / probable / suspected / unverified / estimated /
  forecast) separate.
* No clinical or treatment content.
* Run `ruff check src tests` and `pytest` before opening a pull request.

By contributing you agree that your contribution is licensed under COSL 1.0.
