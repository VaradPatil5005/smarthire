# Compliance notes

This is a deployment planning checklist, not a compliance certification. The customer's privacy
owner and legal advisers must determine which laws apply to the intended use, data flows and
jurisdictions. The demo uses synthetic data only. Sources below were checked on 10 November 2026.

| Regime | What the build already does | What a deployment still needs |
| --- | --- | --- |
| India DPDP Act and Rules 2025 | Upload notice, correction/deletion request recording, logs without resume contents | Confirm applicable phased commencement provisions, parties' roles, processing basis, retention periods and a verified deletion process including backups. A request button does not perform deletion. [1] |
| CERT-In directions | Application logs avoid resume contents | Determine covered-entity obligations, an incident process and the required point of contact. The directions require covered entities to keep ICT logs securely for 180 days within India. [2] |
| EU AI Act | Explainable scores, human review and versioned inputs | Determine whether this implementation and intended use meet the AI-system and high-risk definitions. Employment matching/ranking is a listed use case. The Commission currently gives 2 December 2027 for these high-risk rules. Human involvement alone does not establish an exemption. [3] |
| GDPR / UK GDPR | Organisational access controls and human review | Assess lawful basis, transparency, data minimisation, rights handling, contracts, automated-decision rules and impact assessment needs. EU/UK law can permit overseas transfers with the appropriate mechanism; it does not impose a blanket requirement to host all candidate data in-region. [4, 5] |
| NYC Local Law 144 | No jurisdiction-specific audit or notice workflow | Determine whether the actual tool and use qualify as an AEDT within scope. Covered use requires the prescribed independent bias audit, publication of information and candidate/employee notices. [6] |

## Retention clocks to agree

Files, derived skills and evidence, run snapshots, exports, logs and backups each need their own
period. A run stores the evidence records it used, so run snapshots must be covered too.

## Known limits

- These controls prove the system resists the attacks tested, not every possible attack.
- Visible false claims are not detected. Verify critical skills by test or interview.
- The child-process scanner has no memory cap on Windows and no network sandbox on a developer
  machine. Deployment must add both.
- PyMuPDF is AGPL. Review its licensing obligations before distributing the code or using it commercially.

## Primary sources

1. [Government of India notification summary and phased implementation](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2190014).
2. [CERT-In directions, 28 April 2022, paragraph iv](https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf).
3. European Commission: [AI Act timeline](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai),
   [employment matching and ranking examples](https://ai-act-service-desk.ec.europa.eu/en/employment-0).
4. [European Data Protection Board international transfers guidance](https://www.edpb.europa.eu/sme/be-compliant/international-data-transfers_en).
5. [UK Information Commissioner's Office international transfers guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/international-transfers/a-brief-guide-to-international-transfers/).
6. [New York City DCWP AEDT guidance and FAQs](https://www.nyc.gov/site/dca/businesses/faq-automated-employment-decision-tools.page).
