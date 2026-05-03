"""Add synthetic memories to live store, run recall comparisons, then clean up.

Forget tombstones in the cache (won't surface in recall). Forget events stay
in the events log — that's the intended audit trail. Run `replay()` if you
want to verify cache consistency.
"""

from __future__ import annotations

from hippocamp.memory import Memory


SYNTHETIC_FACTS = [
    # Family / Alex
    "Alex enjoys playing chess in addition to crosswords.",
    "Alex started a new role at Acme Corp in September 2025.",
    "Alex's favorite color is blue.",
    "Sam commutes by bicycle each weekday morning.",
    "Alex has been learning Italian since age 28.",
    # Dev environment
    "Sam's primary editor is Neovim.",
    "Sam uses macOS on a MacBook Pro.",
    "Sam prefers Python over JavaScript for backend work.",
    "The Hippocamp project uses uv for dependency management.",
    # Project release / facts
    "Hippocamp v0.3.4 shipped on 2026-05-02.",
    "Hippocamp uses BAAI/bge-small-en-v1.5 for embeddings by default.",
    "Hippocamp's storage path defaults to ~/.hippocamp/store.db.",
    # Unrelated trivia (control)
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
]


def fmt(r) -> str:
    text = r.text if len(r.text) <= 65 else r.text[:62] + "..."
    return f"  [{r.score:.3f}] sim={r.why.similarity:.2f} sal={r.why.salience:.2f} {r.kind:10}  {text}"


def main() -> None:
    mem = Memory(path="~/.hippocamp")

    before = mem.inspect()
    print(f"baseline inventory: {before.episodes}ep / {before.facts}fa / {before.preferences}pr")

    inserted: list[str] = []
    try:
        for text in SYNTHETIC_FACTS:
            inserted.append(mem.assert_fact(text))
        for text in SYNTHETIC_PREFS:
            inserted.append(mem.assert_preference(text))

        mid = mem.inspect()
        print(f"after insert:        {mid.episodes}ep / {mid.facts}fa / {mid.preferences}pr "
              f"(+{len(inserted)} memories)\n")

        for q in QUERIES:
            print(f"query: {q!r}")
            for r in mem.recall(q, limit=5):
                print(fmt(r))
            print()

    finally:
        for mem_id in inserted:
            mem.forget(mem_id)

        after = mem.inspect()
        print(f"after cleanup:       {after.episodes}ep / {after.facts}fa / {after.preferences}pr")
        ok = (
            after.episodes == before.episodes
            and after.facts == before.facts
            and after.preferences == before.preferences
        )
        print(f"clean: {'YES' if ok else 'NO — inventory mismatch!'}")


if __name__ == "__main__":
    main()
