# Seamless CAD — Documentation

**Read it as a website: <https://hinatahugu29.github.io/Blender_Seamless_CAD/>**

The site has search and a language switcher. The Markdown below is the same
content, readable directly on GitHub.

| Language | Coverage | |
|---|---|---|
| **English** | Full documentation. **Source of truth** | [Read](en/index.md) |
| **日本語** | Full translation | [読む](ja/index.md) |
| **Русский** | Quick Start only. AI translation, not reviewed by a native speaker | [Читать](ru/index.md) |
| **中文** | Quick Start only. AI translation, not reviewed by a native speaker | [阅读](zh/index.md) |

English is the source of truth because the add-on's interface is in English.
Where a translation and the English version disagree, the English version is
correct.

---

## For contributors

- Translation policy, scope per language, and update order:
  [CONTRIBUTING.md](CONTRIBUTING.md)
- Building the site locally:

  ```bash
  py -m pip install -r docs/requirements.txt
  py -m mkdocs serve
  ```

  Then open <http://127.0.0.1:8000/>.

The site is built and published automatically by
[`.github/workflows/docs.yml`](../.github/workflows/docs.yml) on every push to
`main` that touches `docs/` or `mkdocs.yml`.
