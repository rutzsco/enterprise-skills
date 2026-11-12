SEED_SKILLS = [
    {
        "id": "incident-response",
        "name": "Incident response",
        "description": "Synthetic playbook for outage severity, escalation, and customer communications.",
        "category": "Operations",
        "guidance": """# Incident response

Synthetic demo policy. Not a real organization's operating procedure.

## Decide the severity
- SEV 1: a full production outage, or at least 20% of active customer accounts cannot use a core workflow and there is no workaround.
- SEV 2: fewer than 20% of accounts are affected and a documented workaround exists.
- If impact or the availability of a workaround is unknown, ask for that information. Do not invent a severity.

## Coordinate the response
- For SEV 1, acknowledge within 5 minutes, assign an incident commander within 10 minutes, and send customer updates every 15 minutes.
- For SEV 2, acknowledge within 15 minutes and send updates every 30 minutes.
- Every update includes known impact, the current mitigation, the next update time, and what is still unknown.
- If there is suspected data exposure, alert the security on-call as well. Never put customer data, credentials, or exploit details in public updates.

## Close the loop
Confirm recovery using the affected customer workflow. Record a timeline and follow-up owners. Do not invent an ETA or say a fix is complete without evidence.
""",
    },
    {
        "id": "software-purchasing",
        "name": "Software purchasing",
        "description": "Synthetic approval rules for annual software spend and sensitive-data reviews.",
        "category": "Finance",
        "guidance": """# Software purchasing

Synthetic demo policy. Amounts are annual committed cost in USD, including required fees.

## Approval rules
- Below $2,500: the department lead approves.
- From $2,500 through $10,000 inclusive: the department lead and Finance approve.
- Above $10,000: Finance and Procurement approve.
- Any tool processing personal or confidential data also requires a security review, regardless of price.

## Before recommending a route
Confirm annual total, currency, renewal terms, and the type of data the tool will process. Do not compare a monthly price directly with the annual thresholds.

## Missing information
No approved-vendor list, purchasing contact, tax treatment, or approval SLA is supplied. Ask for these when relevant rather than inventing them. These rules describe approvals; they do not authorize the assistant to buy anything.
""",
    },
    {
        "id": "customer-recovery",
        "name": "Customer recovery",
        "description": "Synthetic guidance for service-credit approvals and a clear, empathetic customer reply.",
        "category": "Customer success",
        "guidance": """# Customer recovery

Synthetic demo playbook for one-time service credits in USD.

## Approval rules
- Up to $100 inclusive: a support lead approves.
- Above $100 through $1,000 inclusive: a support manager approves.
- Above $1,000: a customer success director approves.
- Confirm the account, documented service impact, requested credit, and any applicable contract terms.
- Do not promise or apply a credit before the required approval. Contract entitlements must be checked separately.

## Draft the response
Acknowledge the impact, state the facts that are confirmed, explain the proposed next step, and identify any approval still needed. Do not invent a resolution date.

## Escalation
If the customer requests a legal commitment, a contractual change, or compensation other than a service credit, route to the account owner. The supplied notes do not define approval rules for those requests.
""",
    },
]
