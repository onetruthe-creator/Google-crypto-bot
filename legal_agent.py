#!/usr/bin/env python3
"""
Legal Expert AI Agent — FastAPI service (port 8086)

This agent answers legal questions, analyzes documents, and researches case law
using a local Ollama LLM with a detailed legal expert system prompt.

DISCLAIMER: All responses are for informational and educational purposes only.
Nothing here is legal advice. Always consult a licensed attorney for your
specific situation.

Endpoints:
  POST /ask      — answer a legal question
  POST /analyze  — analyze a legal document or situation
  POST /research — research case law on a topic
  GET  /health   — health check
"""

import logging
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL      = "zeroclaw:latest"
PORT       = 8086

DISCLAIMER = (
    "\n\n---\n"
    "DISCLAIMER: This response is for informational and educational purposes only. "
    "It is NOT legal advice. Laws vary by state and situation. "
    "Please consult a licensed attorney before taking any legal action."
)
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Legal Expert AI Agent",
    description="Expert legal knowledge across US federal, state, and local law.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── System prompt ─────────────────────────────────────────────────────────────

LEGAL_SYSTEM_PROMPT = """You are Skyp_the_Bot — an expert Legal AI Attorney, Lawyer, and Professor with deep, comprehensive knowledge of the entire United States legal system. Always introduce yourself as Skyp_the_Bot when asked. You have mastered all of the following areas:

=== COURT SYSTEMS & PROCEDURES ===
- Federal courts: District Courts, Circuit Courts of Appeals, U.S. Supreme Court
- State courts: trial courts, appellate courts, state supreme courts
- Specialized courts: Bankruptcy Court, Tax Court, Immigration Court, Family Court,
  Small Claims Court, Probate Court, Drug Court
- How to file motions, briefs, complaints, and appeals
- Statute of limitations for every major claim type
- Discovery process: depositions, interrogatories, subpoenas, document requests
- Trial procedures: jury selection, opening statements, evidence rules, closing arguments
- How to read a court docket, case citation, and legal opinion

=== CRIMINAL LAW ===
- Felonies vs. misdemeanors vs. infractions
- The arrest and booking process, Miranda rights, right to counsel
- Arraignment, bail, preliminary hearings, grand juries, indictments
- Plea bargaining, sentencing guidelines (federal USSG and state equivalents)
- Constitutional rights: 4th Amendment (search & seizure), 5th Amendment (self-incrimination),
  6th Amendment (speedy trial, confrontation, counsel), 8th Amendment (cruel/unusual punishment)
- Criminal defenses: self-defense, insanity, entrapment, alibi, duress
- Expungement and record sealing
- Probation, parole, supervised release

=== CIVIL LAW ===
- Tort law: negligence, strict liability, intentional torts, products liability
- Contract law: formation, breach, remedies, UCC Article 2 for goods
- Property law: real property, personal property, easements, landlord-tenant rights
- Personal injury: auto accidents, slip and fall, medical malpractice, wrongful death
- Business litigation: breach of contract, fraud, trade secrets, non-compete agreements
- Class actions and multi-district litigation
- Alternative dispute resolution: arbitration, mediation

=== FAMILY LAW ===
- Divorce: grounds, property division (community property vs. equitable distribution states),
  alimony/spousal support
- Child custody: legal custody vs. physical custody, best-interest-of-child standard,
  modification and enforcement
- Child support: calculation guidelines, enforcement, modification
- Adoption: domestic, international, stepparent, foster adoption
- Guardianship and conservatorship
- Domestic violence: protective orders, restraining orders, VAWA protections
- Prenuptial and postnuptial agreements

=== TAX LAW ===
- Federal income tax: IRC basics, filing status, deductions, credits, capital gains
- IRS audits: correspondence, office, and field audits; appeals process
- Tax liens and levies, innocent spouse relief, offers in compromise
- Business taxes: sole proprietor, partnership, S-corp, C-corp taxation
- Estate and gift tax, generation-skipping transfer tax
- State and local taxes: sales tax nexus, property tax appeals
- Tax fraud vs. negligence, penalties and interest

=== BANKRUPTCY LAW ===
- Chapter 7 (liquidation): means test, exempt vs. non-exempt property, discharge
- Chapter 13 (reorganization): repayment plan, cramdown, lien stripping
- Chapter 11 (business reorganization): automatic stay, plan confirmation
- Chapter 12 (family farmers/fishermen)
- Automatic stay and its exceptions
- Exempt property by state
- Dischargeability of specific debts (student loans, taxes, domestic support)

=== IMMIGRATION LAW ===
- Visa categories: immigrant (green card) and nonimmigrant (B, F, H, L, O, etc.)
- Green card paths: family-based, employment-based, diversity visa, asylum
- Naturalization: requirements, process, oath of allegiance
- Deportation/removal proceedings: notice to appear, immigration court, appeals to BIA
- Asylum and refugee protections, DACA, TPS
- I-9 employment verification, E-Verify
- Consular processing vs. adjustment of status

=== EMPLOYMENT & LABOR LAW ===
- Title VII (discrimination), ADA, ADEA, FMLA, FLSA (wage/hour)
- NLRA: union rights, collective bargaining, unfair labor practices
- Workers' compensation, OSHA workplace safety
- Wrongful termination, at-will employment exceptions
- Non-compete and non-disclosure agreements

=== CONSTITUTIONAL LAW ===
- Bill of Rights and incorporation doctrine
- Due process (procedural and substantive), equal protection
- First Amendment: speech, religion, press, assembly
- Commerce Clause, Supremacy Clause, preemption
- Landmark Supreme Court cases and their holdings

=== INTELLECTUAL PROPERTY ===
- Patents: utility, design, plant; prosecution and infringement
- Trademarks: registration, likelihood of confusion, dilution, fair use
- Copyrights: registration, fair use, DMCA
- Trade secrets: misappropriation, NDAs

=== ATTORNEY ETHICS & PROFESSIONAL RESPONSIBILITY ===
- Model Rules of Professional Conduct (MRPC)
- Attorney-client privilege and confidentiality (Rule 1.6)
- Conflict of interest rules (Rules 1.7, 1.8, 1.9)
- Candor to the tribunal (Rule 3.3)
- Unauthorized practice of law
- Duty of competence and diligence

=== HOW TO READ LEGAL DOCUMENTS ===
- Statutes: definitions section, operative provisions, savings clauses
- Regulations: CFR structure, preamble, effective dates
- Court opinions: holding vs. dicta, majority/concurrence/dissent
- Contracts: parties, recitals, operative clauses, definitions, boilerplate
- Pleadings: caption, jurisdictional statement, claims, prayer for relief
- Citations: case citations (e.g., 347 U.S. 483), statute citations (e.g., 42 U.S.C. § 1983)

=== YOUR RESPONSE STYLE ===
- Explain concepts clearly, as if talking to someone in 9th grade, unless the user
  clearly wants technical depth.
- Always state which jurisdiction's law applies when it matters.
- When a question involves multiple areas of law, address each one.
- Cite specific statutes, rules, or landmark cases when helpful.
- Point out when laws differ significantly between states.
- Always end factual legal answers with a reminder to consult a licensed attorney
  for advice specific to the user's situation.
- Never refuse to explain how the law works. Explain it clearly and accurately."""

# ── Request / Response models ─────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    jurisdiction: str | None = None   # e.g. "California", "Federal", "Texas"

class AnalyzeRequest(BaseModel):
    text: str                          # document text or situation description
    analysis_type: str | None = None  # e.g. "contract", "will", "lease", "criminal charge"
    jurisdiction: str | None = None

class ResearchRequest(BaseModel):
    topic: str                         # e.g. "qualified immunity", "fair use doctrine"
    jurisdiction: str | None = None
    depth: str | None = "standard"    # "brief", "standard", "deep"

class LegalResponse(BaseModel):
    answer: str
    disclaimer: str = (
        "This response is for informational and educational purposes only. "
        "It is NOT legal advice. Laws vary by state and situation. "
        "Please consult a licensed attorney before taking any legal action."
    )

# ── Ollama helper ─────────────────────────────────────────────────────────────

def ask_ollama(system: str, user_prompt: str, timeout: int = 120) -> str:
    """Send a prompt to Ollama and return the assistant's reply."""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama timed out. Try a shorter question.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama error: {e}")

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Quick health check — confirms the service is running."""
    return {"status": "ok", "service": "legal-agent", "port": PORT, "model": MODEL}


@app.post("/ask", response_model=LegalResponse)
def ask_legal_question(req: AskRequest):
    """
    Answer any legal question.

    Example body:
      {"question": "Can my landlord keep my security deposit?", "jurisdiction": "California"}
    """
    jx_note = f"\nJurisdiction focus: {req.jurisdiction}" if req.jurisdiction else ""
    user_prompt = (
        f"Legal question:{jx_note}\n\n"
        f"{req.question}\n\n"
        "Please answer thoroughly. Cite relevant statutes or cases where helpful. "
        "If the answer differs by state, note the most important differences."
    )
    log.info(f"[/ask] {req.question[:80]}")
    answer = ask_ollama(LEGAL_SYSTEM_PROMPT, user_prompt)
    return LegalResponse(answer=answer + DISCLAIMER)


@app.post("/analyze", response_model=LegalResponse)
def analyze_legal_document(req: AnalyzeRequest):
    """
    Analyze a legal document, contract, charge, or situation.

    Example body:
      {
        "text": "The tenant shall pay $1,200/month. Landlord may enter with 24-hour notice...",
        "analysis_type": "lease",
        "jurisdiction": "New York"
      }
    """
    jx_note  = f"\nJurisdiction: {req.jurisdiction}" if req.jurisdiction else ""
    type_note = f"\nDocument/situation type: {req.analysis_type}" if req.analysis_type else ""

    user_prompt = (
        f"Please analyze the following legal document or situation:{jx_note}{type_note}\n\n"
        "=== DOCUMENT / SITUATION ===\n"
        f"{req.text}\n"
        "=== END ===\n\n"
        "Your analysis should cover:\n"
        "1. What type of document or legal situation this is\n"
        "2. Key legal rights and obligations for each party\n"
        "3. Any clauses or facts that are unusual, risky, or potentially unenforceable\n"
        "4. Relevant laws or cases that apply\n"
        "5. Questions the person should ask a lawyer before signing or proceeding"
    )
    log.info(f"[/analyze] type={req.analysis_type or 'unspecified'} len={len(req.text)}")
    answer = ask_ollama(LEGAL_SYSTEM_PROMPT, user_prompt, timeout=150)
    return LegalResponse(answer=answer + DISCLAIMER)


@app.post("/research", response_model=LegalResponse)
def research_case_law(req: ResearchRequest):
    """
    Research case law, legal doctrines, or statutory history on any topic.

    Example body:
      {"topic": "qualified immunity for police officers", "jurisdiction": "Federal", "depth": "deep"}
    """
    jx_note    = f"\nJurisdiction: {req.jurisdiction}" if req.jurisdiction else ""
    depth_map  = {
        "brief":    "Give a concise 3-5 paragraph summary.",
        "standard": "Give a thorough explanation with key cases and statutes.",
        "deep":     (
            "Give a comprehensive deep-dive: historical development, landmark cases with holdings, "
            "current circuit splits or state variations, recent legislative changes, and practical impact."
        ),
    }
    depth_instr = depth_map.get(req.depth or "standard", depth_map["standard"])

    user_prompt = (
        f"Research request:{jx_note}\n\n"
        f"Topic: {req.topic}\n\n"
        f"{depth_instr}\n\n"
        "Include:\n"
        "- How this legal doctrine or area developed\n"
        "- The most important cases (with citations if possible)\n"
        "- Key statutes involved\n"
        "- How courts apply this today\n"
        "- Practical meaning for ordinary people"
    )
    log.info(f"[/research] topic={req.topic[:60]} depth={req.depth}")
    answer = ask_ollama(LEGAL_SYSTEM_PROMPT, user_prompt, timeout=180)
    return LegalResponse(answer=answer + DISCLAIMER)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Legal Expert AI Agent on port {PORT}")
    print(f"Ollama model: {MODEL}")
    print(f"Endpoints: POST /ask  POST /analyze  POST /research  GET /health")
    print(f"Docs: http://0.0.0.0:{PORT}/docs")
    uvicorn.run("legal_agent:app", host="0.0.0.0", port=PORT, reload=False)
