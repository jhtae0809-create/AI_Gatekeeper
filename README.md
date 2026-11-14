# AI Gatekeeper

A gatekeeper that decides whether an LLM prompt and answer record is safe to keep before it goes into a permanent record, such as a blockchain. A record is risky if it holds personal information (PII), a credential, or harmful content.

| Folder | What it holds |
|---|---|
| [experiments/](experiments/) | Test set, gate experiments and results. Start with [experiments/README.md](experiments/README.md); full write-up in [experiments/docs/code_walkthrough.md](experiments/docs/code_walkthrough.md) |
| [mvp/](mvp/) | A working demo: a senior care companion whose gateway masks each record before it leaves the home; a stored record goes on the Sepolia blockchain once a person permits it. Start with [mvp/README.md](mvp/README.md) |
