# Third-party materials

The project code, example scripts (including Tidelight's story), documentation
and original example data are licensed under the root [MIT license](LICENSE).
Third-party software and fonts retain their own licenses.

- SQLAlchemy, greenlet, typing_extensions, pysqlite3-binary, and optionally
  DuckDB / duckdb-engine are installed from the exact versions and hashes in
  `uv.lock`. Their license texts remain in the installed packages. The staging
  tool creates `DEPENDENCIES.json` with the actual versions and license paths.
- SQLite is in the public domain; the pysqlite3 binary distribution also
  contains Python-derived code with its own notices.
- Logica is a development-time compiler, not bundled with the games.
- Tidelight Sans is a renamed subset of Noto Sans CJK SC, copyright
  2014–2021 Adobe, under SIL Open Font License 1.1. See
  [font source and license](examples/tidelight/game/fonts/README.md).
- Standalone playable distributions include an unmodified Ren'Py runtime.
  Their `LICENSE.txt` contains Ren'Py's notices and licenses, including those
  of its native dependencies. Keep this file with the distribution. The
  upstream source links are provided by the
  [Ren'Py license documentation](https://www.renpy.org/doc/html/license.html)
  and the pinned [8.5.3 release](https://www.renpy.org/release/8.5.3).

No third-party illustrations, music, voice acting, or character artwork are
bundled with these text-only examples.
