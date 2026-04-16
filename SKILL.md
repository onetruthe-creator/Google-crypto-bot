# Skill: legal-expert

## Description
Expert Legal AI Agent covering the entire US legal system — federal, state, and
local law. Handles criminal law, civil law, family law, tax law, bankruptcy,
immigration, employment law, constitutional law, intellectual property, and
attorney ethics. Also reads and analyzes legal documents, court opinions,
contracts, and leases.

**DISCLAIMER: All responses are for informational and educational purposes only.
They are NOT legal advice. Users should consult a licensed attorney for their
specific situation.**

---

## Trigger Phrases
Route a message to this skill when it contains any of the following:

- Starts with `legal:` (highest priority — always route here)
- Any question about laws, courts, charges, crimes, lawsuits, rights
- Words like: lawsuit, attorney, lawyer, court, judge, jury, verdict, arrest,
  criminal, felony, misdemeanor, indictment, plea, bail, probation, parole,
  divorce, custody, alimony, child support, restraining order, eviction,
  landlord, tenant, bankruptcy, foreclosure, immigration, visa, green card,
  deportation, IRS, tax audit, will, estate, trademark, copyright, patent,
  contract, settlement, damages, injunction, subpoena, deposition, appeal
- Phrases like: "is it legal to", "can I sue", "what are my rights",
  "how does [law/court/process] work", "analyze this contract",
  "what does this mean legally", "can I be arrested for", "legal help"

---

## Endpoints

Base URL: `http://127.0.0.1:8086`

### POST /ask
Answer any legal question.

**Request body:**
```json
{
  "question": "Can my landlord keep my security deposit?",
  "jurisdiction": "California"
}
```
- `question` (required): The user's legal question in plain English.
- `jurisdiction` (optional): State name, "Federal", or city/county if known.
  If not provided, the agent will note where law varies by state.

**Response:**
```json
{
  "answer": "Under California Civil Code § 1950.5, your landlord must...",
  "disclaimer": "This response is for informational and educational purposes only..."
}
```

---

### POST /analyze
Analyze a legal document (contract, lease, court order, charge, will, etc.)
or describe a legal situation for analysis.

**Request body:**
```json
{
  "text": "The tenant shall pay $1,200/month. Landlord may enter with 24-hour notice...",
  "analysis_type": "lease",
  "jurisdiction": "New York"
}
```
- `text` (required): Full text of the document OR a description of the situation.
- `analysis_type` (optional): `contract`, `lease`, `will`, `criminal charge`,
  `court order`, `lawsuit`, `plea deal`, `police report`, `immigration notice`, etc.
- `jurisdiction` (optional): State or "Federal".

**Response:** Same format as `/ask`. Analysis covers key rights, risky clauses,
applicable laws, and questions to ask a lawyer.

---

### POST /research
Research a legal doctrine, area of law, or topic in case law history.

**Request body:**
```json
{
  "topic": "qualified immunity for police officers",
  "jurisdiction": "Federal",
  "depth": "deep"
}
```
- `topic` (required): Any legal concept, doctrine, statute, or case area.
- `jurisdiction` (optional): State or "Federal".
- `depth` (optional): `"brief"` (short summary), `"standard"` (default, thorough),
  `"deep"` (full historical deep-dive with cases and circuit splits).

---

### GET /health
Returns `{"status": "ok", "service": "legal-agent", "port": 8086, "model": "llama3.2:1b"}`

---

## Routing Rules for ZeroClaw

```
IF message starts with "legal:" THEN
    strip the "legal:" prefix
    POST /ask with the remaining text as "question"
    return the "answer" field

IF message contains legal document text AND user asks to review/analyze/explain it THEN
    POST /analyze with text and detected type

IF message asks about a legal doctrine, history of a law, or case law THEN
    POST /research with the topic

ALL OTHER legal questions THEN
    POST /ask
```

Always include the `disclaimer` field from the response at the end of every reply.

---

## Response Format Template

When relaying a legal answer to the user, use this format:

```
[Legal Expert]

{answer}

---
DISCLAIMER: {disclaimer}
```

If the answer is long, you may summarize the main points first, then give the
full answer below a "Full explanation:" header.

---

## Error Handling

- If the agent returns HTTP 504: Reply "The legal agent is taking too long. Try
  rephrasing your question more briefly."
- If the agent returns HTTP 502 or 500: Reply "The legal agent is temporarily
  unavailable. Please try again in a moment."
- If Ollama is not running: The service cannot start. Run `ollama serve` and
  ensure the `llama3.2:1b` model is pulled (`ollama pull llama3.2:1b`).

---

## Knowledge Areas (for routing confidence)

| Area                    | Route Here? |
|-------------------------|-------------|
| US Federal law          | Yes         |
| State law (any state)   | Yes         |
| Local ordinances        | Yes         |
| Criminal law            | Yes         |
| Civil litigation        | Yes         |
| Family law              | Yes         |
| Tax law / IRS           | Yes         |
| Bankruptcy              | Yes         |
| Immigration             | Yes         |
| Employment law          | Yes         |
| Constitutional law      | Yes         |
| Intellectual property   | Yes         |
| Attorney ethics         | Yes         |
| Contract analysis       | Yes         |
| Court procedures        | Yes         |
| Non-US foreign law      | No — decline and explain US law only |
| Financial trading       | No — route to maxmillion-trader skill |

---

## Notes

- The agent runs on a Jetson computer at `http://127.0.0.1:8086`.
- It uses Ollama with `llama3.2:1b` as the LLM backend.
- Response times: `/ask` ~30-60s, `/analyze` ~60-90s, `/research` ~60-120s.
- All responses automatically include a legal disclaimer. Always show it.
- This agent does NOT provide legal advice and cannot represent anyone in court.
  Its purpose is legal education and information.
