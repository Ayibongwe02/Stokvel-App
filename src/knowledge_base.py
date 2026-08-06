"""
Knowledge base for the AI assistant
====================================
This is the piece that makes the assistant actually "trained on this
application" in the way that matters: not a fine-tuned model, but a
curated set of documents — half about how this specific app works,
half about stokvel/savings-group financial best practice — retrieved
by relevance to the member's question and injected into the prompt.

Retrieval is plain TF-IDF + cosine similarity, hand-rolled with numpy
so this has zero extra dependencies beyond what the app already ships
with. That's plenty for a knowledge base this size (a few dozen
chunks) — no vector database needed.
"""

import math
import re
from collections import Counter

import numpy as np

DOCS = [
    {
        "id": "app-groups",
        "category": "app",
        "title": "Groups and invite codes",
        "text": (
            "Every member belongs to one or more groups, joined via an invite code. "
            "An admin can regenerate a group's invite code from Settings if it's been "
            "shared too widely. You can belong to more than one group and switch "
            "between them from the group selector in the navigation."
        ),
    },
    {
        "id": "app-roles",
        "category": "app",
        "title": "Member vs admin roles",
        "text": (
            "Each group has members and admins. Admins can edit group settings "
            "(contribution rules, payout rules, withdrawal approval thresholds), "
            "remove members, and approve or reject withdrawal requests. Regular "
            "members can view forecasts, contribute, and request withdrawals, but "
            "cannot change group-wide settings."
        ),
    },
    {
        "id": "app-forecast",
        "category": "app",
        "title": "Member Forecast page",
        "text": (
            "The Forecast page fits a Holt-Winters model live on "
            "a member's own contribution and withdrawal history, and shows a 95% "
            "confidence band a few periods into the future. A widening confidence "
            "band usually means that member's contributions have become irregular — "
            "the model is less sure what happens next because the pattern itself is "
            "less predictable."
        ),
    },
    {
        "id": "app-accuracy",
        "category": "app",
        "title": "Accuracy Health Settings",
        "text": (
            "The Accuracy Health Settings section, inside Settings, backtests the "
            "Holt-Winters model against a member's real history, "
            "reporting RMSE, MAE, and MAPE. Use it to see how reliable the "
            "forecast is for a given member's pattern rather than trusting it "
            "blindly — members with irregular contribution patterns will show "
            "higher error than members with steady, predictable ones."
        ),
    },
    {
        "id": "app-payments",
        "category": "app",
        "title": "Contributing via Payments",
        "text": (
            "Contributions are made on the Payments page via PayFast's hosted "
            "checkout — card or Instant EFT. A contribution shows as 'pending' "
            "until PayFast confirms it, which is usually a matter of seconds but "
            "can occasionally take longer for EFT payments, since bank confirmation "
            "isn't instant the way card payments are."
        ),
    },
    {
        "id": "app-withdrawals",
        "category": "app",
        "title": "Requesting and approving withdrawals",
        "text": (
            "Any member can request a withdrawal from the Payments page. It needs "
            "sign-off from the group's configured number of admins (1-3, set in "
            "Group Settings) before it moves to 'approved', and an admin marks it "
            "'paid' once the payout is actually sent. Large withdrawals above the "
            "group's configured threshold can require extra approvals automatically."
        ),
    },
    {
        "id": "app-group-settings",
        "category": "app",
        "title": "Group settings admins can configure",
        "text": (
            "From Settings, an admin sets the group's agreed contribution amount "
            "and frequency, writes down payout/rotation rules in plain text, and "
            "sets how many admin approvals a withdrawal needs (with an optional "
            "higher threshold for large amounts). Getting these written down early "
            "avoids disputes later."
        ),
    },
    {
        "id": "practice-consistency",
        "category": "practice",
        "title": "Consistency beats size",
        "text": (
            "For a savings group, consistent contribution timing predicts total "
            "balance growth far more reliably than contribution size. A member who "
            "contributes a smaller amount every single period will usually end up "
            "ahead of one who contributes more but skips periods, because missed "
            "contributions compound — the group loses both that period's amount "
            "and the growth it would have earned."
        ),
    },
    {
        "id": "practice-missed-contributions",
        "category": "practice",
        "title": "Missed contributions are the leading risk",
        "text": (
            "Irregular or missed contributions are the single most common reason "
            "stokvels underperform their own savings targets — more common than "
            "market conditions or poor investment choices. Catching a pattern of "
            "missed contributions early, and having an honest conversation with "
            "that member, protects the whole group's payout schedule."
        ),
    },
    {
        "id": "practice-payout-rules",
        "category": "practice",
        "title": "Agree payout rules before you need them",
        "text": (
            "Rotating payout schedules, withdrawal conditions, and what happens if "
            "a member leaves early should be agreed and written down before "
            "there's a dispute, not after. Groups that formalize this early "
            "(constitution, written rules) have far fewer conflicts than groups "
            "relying on verbal agreements."
        ),
    },
    {
        "id": "practice-emergency-fund",
        "category": "practice",
        "title": "Separate emergency needs from the group pot",
        "text": (
            "Financial advisors generally recommend members keep some individual "
            "emergency savings outside the stokvel, rather than relying on early "
            "withdrawal from the group pot for emergencies. Early withdrawals "
            "disrupt the group's compounding and can strain relationships if they "
            "become frequent."
        ),
    },
    {
        "id": "practice-diversify",
        "category": "practice",
        "title": "Don't treat one stokvel as your whole plan",
        "text": (
            "A stokvel is a strong savings discipline tool but works best as one "
            "part of a broader financial plan, not the only one. Members are "
            "generally better served spreading savings across a stokvel, some "
            "individual savings, and (where possible) retirement or investment "
            "vehicles, rather than concentrating everything in the group."
        ),
    },
    {
        "id": "practice-record-keeping",
        "category": "practice",
        "title": "Record-keeping protects everyone",
        "text": (
            "Clear, member-visible records of who contributed what and when "
            "protect both the group and individual members from disputes and "
            "misunderstandings. Digital record-keeping (like this app's "
            "transaction history) is a meaningful upgrade over informal "
            "notebook-based tracking, which is harder to audit after the fact."
        ),
    },
    {
        "id": "practice-legal-tax",
        "category": "practice",
        "title": "Legal and tax questions need a professional",
        "text": (
            "Stokvels can have specific legal structuring and tax considerations "
            "depending on size and jurisdiction. This is genuinely worth a "
            "qualified accountant or advisor's input rather than general guidance "
            "— the right structure depends on details specific to your group that "
            "a general chatbot can't verify."
        ),
    },
    {
        "id": "practice-red-flags",
        "category": "practice",
        "title": "Red flags in savings-group schemes",
        "text": (
            "Be cautious of any group promising unusually high, guaranteed "
            "returns, requiring new members to recruit others to get paid "
            "(pyramid structure), or resisting transparent record-keeping. "
            "Legitimate stokvels are pooled savings with agreed rules, not "
            "investment vehicles promising outsized guaranteed returns."
        ),
    },
]


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "from", "had", "has", "have", "how", "i", "if", "in", "is",
    "it", "its", "of", "on", "or", "that", "the", "this", "to", "was",
    "what", "when", "where", "why", "will", "with", "you", "your",
}


def _stem(token: str) -> str:
    """Deliberately crude suffix-stripping stemmer — good enough for a
    knowledge base this size, and avoids pulling in nltk just for this."""
    if token.endswith("ss"):
        return token
    for suffix in ("ing", "edly", "ed", "ies", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9']+", text.lower())
    return [_stem(tok) for tok in raw if tok not in _STOPWORDS]


_corpus_tokens = [_tokenize(d["title"] + " " + d["text"]) for d in DOCS]
_vocab = sorted({tok for toks in _corpus_tokens for tok in toks})
_vocab_index = {tok: i for i, tok in enumerate(_vocab)}
_n_docs = len(DOCS)

_doc_freq = Counter()
for toks in _corpus_tokens:
    for tok in set(toks):
        _doc_freq[tok] += 1

_idf = np.array(
    [math.log((1 + _n_docs) / (1 + _doc_freq[tok])) + 1 for tok in _vocab]
)


def _tfidf_vector(tokens: list[str]) -> np.ndarray:
    vec = np.zeros(len(_vocab))
    counts = Counter(tokens)
    for tok, count in counts.items():
        idx = _vocab_index.get(tok)
        if idx is not None:
            vec[idx] = count
    vec = vec * _idf
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


_doc_vectors = np.array([_tfidf_vector(toks) for toks in _corpus_tokens])


def search(query: str, k: int = 4) -> list[dict]:
    """Returns the top-k most relevant docs for a query, each with a
    similarity score. Pure cosine similarity over TF-IDF vectors —
    no external service, no API call, works even fully offline."""
    query_vec = _tfidf_vector(_tokenize(query))
    if not np.any(query_vec):
        return []
    scores = _doc_vectors @ query_vec
    top_indices = np.argsort(scores)[::-1][:k]
    results = []
    for i in top_indices:
        if scores[i] <= 0:
            continue
        results.append({**DOCS[i], "score": float(scores[i])})
    return results
