"""Compare embedders on the same corpus, queries, and ranker.

Builds a fresh in-memory store for each embedder, inserts the same set of
memories, runs the same queries. Salience starts at 0 for every memory in
both runs, so this isolates pure semantic-recall quality.
"""

from __future__ import annotations

from hippocamp.embedders import BgeSmallEmbedder
from hippocamp.memory import Memory


# Synthetic corpus mirroring a realistic mixed-domain memory store.
EXISTING_FACTS = [
    "Alex is Sam's colleague. They have worked together since April 2026.",
    'User uses another personal assistant called "AcmeAssist" — some Hippocamp facts (e.g. about Alex) originated there, demonstrating Hippocamp\'s portability across hosts.',
    "User's project uses Python 3.13.",
    "Hippocamps are mythological creatures that are half-horse and half-fish.",
    "The brain's hippocampus is named after the hippocampus (hippocamp), the half-horse, half-fish mythological creature — its curved shape resembles the creature.",
    "Hippocamps (half-horse, half-fish mythological creatures) should never be confused with hippopotamuses (the large semi-aquatic African mammals).",
    "Alex (Sam's colleague) loves to play chess.",
    "Alex (Sam's colleague, working together since April 2026) likes the game chess.",
    "Alex (Sam's colleague) is currently leading the onboarding redesign as of May 2026, working on user-research interviews and synthesis. Uses Figma and Notion for documentation.",
]

EXISTING_PREFS = [
    "User prefers terse replies.",
]

EXISTING_EPISODES = [
    "this came from a peer device",
    "Sam started a new fitness routine this week.",
]

SYNTHETIC_FACTS = [
    "Alex enjoys playing chess in addition to crosswords.",
    "Alex started a new role at Acme Corp in September 2025.",
    "Alex's favorite color is blue.",
    "Sam commutes by bicycle each weekday morning.",
    "Alex has been learning Italian since age 28.",
    "Sam's primary editor is Neovim.",
    "Sam uses macOS on a MacBook Pro.",
    "Sam prefers Python over JavaScript for backend work.",
    "The Hippocamp project uses uv for dependency management.",
    "Hippocamp v0.3.4 shipped on 2026-05-02.",
    "Hippocamp uses BAAI/bge-small-en-v1.5 for embeddings by default.",
    "Hippocamp's storage path defaults to ~/.hippocamp/store.db.",
    "The Eiffel Tower is in Paris, France.",
    "The capital of Japan is Tokyo.",
    "Water boils at 100 degrees Celsius at sea level.",
    "Python 3.13 introduced experimental free-threaded mode without the GIL.",
    "Apache 2.0 is a permissive open-source license.",
]

SYNTHETIC_PREFS = [
    "Sam prefers concise documentation over verbose docs.",
    "Sam dislikes tools that require mandatory cloud accounts.",
]

QUERIES = [
    "what does Alex enjoy",
    "Alex's hobbies",
    "user's colleagues",
    "what editor does Sam use",
    "where is the Eiffel Tower",
    "what does Sam prefer for code",
    "Hippocamp release history",
    "Sam's daily routine",
    "open source license",
    "user's colleague interests",
]


class Qwen3Embedder:
    """Qwen3-Embedding-0.6B local embedder (sentence-transformers compatible)."""

    name = "Qwen3-Embedding-0.6B"
    dim = 1024

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

    def __call__(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()


def populate(mem: Memory) -> None:
    for text in EXISTING_FACTS + SYNTHETIC_FACTS:
        mem.assert_fact(text)
    for text in EXISTING_PREFS + SYNTHETIC_PREFS:
        mem.assert_preference(text)
    for text in EXISTING_EPISODES:
        mem.observe(text)


def fmt(r) -> str:
    text = r.text if len(r.text) <= 65 else r.text[:62] + "..."
    return f"  [{r.score:.3f}] sim={r.why.similarity:.2f} {r.kind:10}  {text}"


def run(label: str, embedder) -> None:
    print(f"\n========================== {label} ==========================")
    mem = Memory(path=":memory:", embedder=embedder)
    populate(mem)
    inv = mem.inspect()
    print(f"corpus: {inv.episodes}ep / {inv.facts}fa / {inv.preferences}pr  "
          f"embedder: {embedder.name} (dim={embedder.dim})")

    for q in QUERIES:
        print(f"\nquery: {q!r}")
        for r in mem.recall(q, limit=5):
            print(fmt(r))


def main() -> None:
    run("BGE-small (current)", BgeSmallEmbedder())
    run("Qwen3-Embedding-0.6B", Qwen3Embedder())


if __name__ == "__main__":
    main()
