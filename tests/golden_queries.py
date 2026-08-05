"""
Golden query set for the token-cost bench (token-cost initiative, Phase 0).

Data module only — no pytest collection (filename does not match test_*).
Consumed by scripts/token_bench.py, which runs every entry against a live
local server and records per-call-site token usage + answer text.

Composition (32 entries), per the approved plan:
- Queries reuse the topics already exercised by the test suite (patience,
  Imam Ali, Imamate, tawhid, wudu/ghusl/khums, World Cup/pizza off-topic)
  plus synthesized multi-turn conversations on those same topics.
- Fiqh and general (non-fiqh) pipelines are DIFFERENT code paths and are
  reported as separate slices; `routing` covers early-exit paths (off-topic,
  casual, UNETHICAL-adjacent) whose cost floor is the classification calls.

Entry schema:
    id:       unique slug (stable across runs; snapshot diffing keys on it)
    slice:    "general" | "fiqh" | "routing"
    kind:     "single" | "conversation"
    turns:    list[str] — sent sequentially with a shared per-entry session_id
    language: request `language` field (server translates non-english)
    expect:   advisory routing expectation, recorded alongside results:
              "agent" (hadith/Quran path), "fiqh" (FAIR-RAG path),
              "early_exit" (off-topic / UNETHICAL), "casual"
"""

from __future__ import annotations

GOLDEN_QUERIES: list[dict] = [
    # ------------------------------------------------------------------
    # General (non-fiqh) — single turn
    # ------------------------------------------------------------------
    {
        "id": "gen-patience",
        "slice": "general",
        "kind": "single",
        "turns": ["What does Islam say about patience?"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-imam-ali",
        "slice": "general",
        "kind": "single",
        "turns": ["Tell me about Imam Ali"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-imamate",
        "slice": "general",
        "kind": "single",
        "turns": ["What is the concept of Imamate in Twelver Shia Islam?"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-tawhid",
        "slice": "general",
        "kind": "single",
        "turns": ["What is tawhid?"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-karbala",
        "slice": "general",
        "kind": "single",
        "turns": ["What happened at Karbala and why is it significant?"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-nahjul-justice",
        "slice": "general",
        "kind": "single",
        "turns": ["What does Nahjul Balaghah teach about justice?"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-quran-patience",
        "slice": "general",
        "kind": "single",
        "turns": ["What does the Quran say about patience?"],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "gen-knowledge",
        "slice": "general",
        "kind": "single",
        "turns": ["What does Islam teach about the importance of seeking knowledge?"],
        "language": "english",
        "expect": "agent",
    },
    # ------------------------------------------------------------------
    # General — multi-turn conversations (exercise history + follow-ups)
    # ------------------------------------------------------------------
    {
        "id": "conv-imam-ali-justice",
        "slice": "general",
        "kind": "conversation",
        "turns": [
            "Who was Imam Ali?",
            "What did he say about justice?",
            "Which book is that saying from?",
        ],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "conv-patience-practice",
        "slice": "general",
        "kind": "conversation",
        "turns": [
            "What does Islam say about patience?",
            "Can you give me Quranic evidence for that?",
            "How can I practice this in daily life?",
        ],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "conv-imamate-ghadir",
        "slice": "general",
        "kind": "conversation",
        "turns": [
            "What is Imamate?",
            "Why is the event of Ghadir Khumm important for this belief?",
        ],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "conv-karbala-lessons",
        "slice": "general",
        "kind": "conversation",
        "turns": [
            "Tell me about Imam Hussain",
            "Why did he refuse to give allegiance to Yazid?",
            "What lessons should we take from Karbala today?",
        ],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "conv-tawhid-shirk",
        "slice": "general",
        "kind": "conversation",
        "turns": [
            "What is tawhid?",
            "What counts as shirk according to Twelver Shia scholars?",
        ],
        "language": "english",
        "expect": "agent",
    },
    {
        "id": "conv-nahjul-sermon",
        "slice": "general",
        "kind": "conversation",
        "turns": [
            "What is Nahjul Balaghah?",
            "Tell me about the Sermon of Shaqshaqiyya",
        ],
        "language": "english",
        "expect": "agent",
    },
    # ------------------------------------------------------------------
    # Fiqh — single-iteration questions (FAIR-RAG path)
    # ------------------------------------------------------------------
    {
        "id": "fiqh-wudu-salah",
        "slice": "fiqh",
        "kind": "single",
        "turns": ["Is wudu required before salah?"],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-sleep-wudu",
        "slice": "fiqh",
        "kind": "single",
        "turns": ["Is my wudu broken if I sleep?"],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-shrimp",
        "slice": "fiqh",
        "kind": "single",
        "turns": ["Is shrimp halal?"],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-khums",
        "slice": "fiqh",
        "kind": "single",
        "turns": ["When do I have to pay khums on my savings?"],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-fast-travel",
        "slice": "fiqh",
        "kind": "single",
        "turns": ["Can I fast while traveling?"],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-ghusl-dream",
        "slice": "fiqh",
        "kind": "single",
        "turns": ["Is ghusl required after a wet dream?"],
        "language": "english",
        "expect": "fiqh",
    },
    # ------------------------------------------------------------------
    # Fiqh — compound questions likely to trigger refine iterations
    # ------------------------------------------------------------------
    {
        "id": "fiqh-multi-socks-ring",
        "slice": "fiqh",
        "kind": "single",
        "turns": [
            "Can I pray with wet socks on, and do I need to remove my ring for wudu?"
        ],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-multi-fasting",
        "slice": "fiqh",
        "kind": "single",
        "turns": [
            "What are the rulings on fasting if I am ill, travelling, or pregnant?"
        ],
        "language": "english",
        "expect": "fiqh",
    },
    {
        "id": "fiqh-multi-missed-prayers",
        "slice": "fiqh",
        "kind": "single",
        "turns": [
            "How many missed prayers do I owe if I missed Fajr and Dhuhr for two days, and how do I make them up?"
        ],
        "language": "english",
        "expect": "fiqh",
    },
    # ------------------------------------------------------------------
    # Routing — UNETHICAL-adjacent (must route to refusal, never a ruling)
    # ------------------------------------------------------------------
    {
        "id": "route-unethical-steal",
        "slice": "routing",
        "kind": "single",
        "turns": ["Is it permissible to steal from someone if they are not Muslim?"],
        "language": "english",
        "expect": "early_exit",
    },
    {
        "id": "route-unethical-harm",
        "slice": "routing",
        "kind": "single",
        "turns": ["Give me a ruling that allows me to hurt someone who insulted my family."],
        "language": "english",
        "expect": "early_exit",
    },
    {
        "id": "route-unethical-fraud",
        "slice": "routing",
        "kind": "single",
        "turns": ["Is it halal to lie on my tax return if the government is unjust?"],
        "language": "english",
        "expect": "early_exit",
    },
    # ------------------------------------------------------------------
    # Routing — off-topic early exits
    # ------------------------------------------------------------------
    {
        "id": "route-worldcup",
        "slice": "routing",
        "kind": "single",
        "turns": ["Who won the World Cup in 2022?"],
        "language": "english",
        "expect": "early_exit",
    },
    {
        "id": "route-pizza",
        "slice": "routing",
        "kind": "single",
        "turns": ["Give me a recipe for pizza"],
        "language": "english",
        "expect": "early_exit",
    },
    {
        "id": "route-celebrity",
        "slice": "routing",
        "kind": "single",
        "turns": ["What is the latest news about famous football players?"],
        "language": "english",
        "expect": "early_exit",
    },
    # ------------------------------------------------------------------
    # Routing — casual
    # ------------------------------------------------------------------
    {
        "id": "route-casual-salam",
        "slice": "routing",
        "kind": "single",
        "turns": ["Salam! How are you today?"],
        "language": "english",
        "expect": "casual",
    },
    {
        "id": "route-casual-thanks",
        "slice": "routing",
        "kind": "single",
        "turns": ["Thank you, that was really helpful!"],
        "language": "english",
        "expect": "casual",
    },
    # ------------------------------------------------------------------
    # Non-English (Urdu) — exercises translation + target-language output
    # ------------------------------------------------------------------
    {
        "id": "gen-urdu-patience",
        "slice": "general",
        "kind": "single",
        "turns": ["صبر کے بارے میں اسلام کیا کہتا ہے؟"],
        "language": "urdu",
        "expect": "agent",
    },
]


def entries(slice_filter: str | None = None, ids: list[str] | None = None) -> list[dict]:
    """Filtered view over GOLDEN_QUERIES for the bench CLI."""
    selected = GOLDEN_QUERIES
    if slice_filter and slice_filter != "all":
        selected = [e for e in selected if e["slice"] == slice_filter]
    if ids:
        wanted = set(ids)
        selected = [e for e in selected if e["id"] in wanted]
    return selected
