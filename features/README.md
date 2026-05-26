# python-vsdx — Behave acceptance tests

Mirrors the `features/` shape used by `python-pptx` and `python-docx`.
Every scenario exercises the public `vsdx` API only — no peeking into
the `oxml` or part layers from this layer. (For unit-level coverage of
internal element classes, see `tests/unit/`.)

## Running the suite

From the package root:

```bash
pip install -e '.[dev]'
pip install behave
behave features/
```

The `behave.ini` next to this directory configures `default_tags = ~@wip`
so out-of-scope scenarios are skipped by default. Run them explicitly
with `behave features/ --tags=@wip` once the feature lands.

## Feature files

| File                  | Surface                                                     |
| --------------------- | ----------------------------------------------------------- |
| `doc.feature`         | `vsdx.Visio()` factory, save/open round-trip, .vsdx vs vssx |
| `page.feature`        | `Pages.add_page` / `remove`, page geometry, background pgs  |
| `shape.feature`       | `ShapeTree.add_shape` for built-in masters                  |
| `connector.feature`   | `ShapeTree.add_connector`, source/target glue, route style  |
| `master.feature`      | `Masters.add_master` / `ensure` / `resolve`                 |
| `text.feature`        | `TextFrame.text`, `paragraphs`, `clear`                     |

## `@wip` scenarios

The following are deliberately collected but not run by default —
each marks an area where the public API is still pending in the
package's published roadmap:

- **`text.feature` — Multiple paragraphs**: 0.1.0 `TextFrame` joins
  paragraphs onto a single `<Text>` body via newline; the
  `<pp/>`-marker machinery to emit real multiple paragraphs is
  scheduled for 0.2.0 (`vsdx/text/text.py:60`).

- **`text.feature` — Per-run formatting**: per-run font / colour /
  size lives in the `<Section N="Character">` row machinery, also
  pending in the oxml layer (`vsdx/text/text.py:100`).

When those features land, drop the `@wip` tag and add a step
implementation under `features/steps/text.py`.

## Adding scenarios

Steps are reusable across features — declare them in the file that
matches the *primary* concept (`document.py` for doc-scope, `page.py`
for page-scope, etc.) and let other feature files reference them by
phrasing. Step phrases must be globally unique within `features/steps/`;
when two features need the same step, host it in the most general
module and `from helpers import ...` to share constants.
